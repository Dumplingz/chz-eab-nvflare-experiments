# Copyright (c) 2023, NVIDIA CORPORATION.  All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os.path

import torch
from pt_constants import PTConstants
from simple_network import CifarNet, MnistNet
from torch import nn
from torch.optim import SGD
from torch.utils.data.dataloader import DataLoader
from torchvision.datasets import CIFAR10, FashionMNIST
from torchvision.transforms import Compose, Normalize, ToTensor
import csv
import time

from nvflare.apis.dxo import DXO, DataKind, MetaKey, from_shareable
from nvflare.apis.executor import Executor
from nvflare.apis.fl_constant import ReservedKey, ReturnCode
from nvflare.apis.fl_context import FLContext
from nvflare.apis.shareable import Shareable, make_reply
from nvflare.apis.signal import Signal
from nvflare.app_common.abstract.model import make_model_learnable, model_learnable_to_dxo
from nvflare.app_common.app_constant import AppConstants
from nvflare.app_opt.pt.model_persistence_format_manager import PTModelPersistenceFormatManager

EPOCH_NUM = 0
SUBSET_SIZE = 7500
BATCH_SIZE = 64
NUM_PARTIES = 2


class MnistTrainer(Executor):
    def __init__(
        self,
        data_path="~/data",
        lr=0.001,
        epochs=5,
        train_task_name=AppConstants.TASK_TRAIN,
        submit_model_task_name=AppConstants.TASK_SUBMIT_MODEL,
        exclude_vars=None,
        pre_train_task_name=AppConstants.TASK_GET_WEIGHTS,
    ):
        """Cifar10 Trainer handles train and submit_model tasks. During train_task, it trains a
        simple network on CIFAR10 dataset. For submit_model task, it sends the locally trained model
        (if present) to the server.

        Args:
            lr (float, optional): Learning rate. Defaults to 0.01
            epochs (int, optional): Epochs. Defaults to 5
            train_task_name (str, optional): Task name for train task. Defaults to "train".
            submit_model_task_name (str, optional): Task name for submit model. Defaults to "submit_model".
            exclude_vars (list): List of variables to exclude during model loading.
            pre_train_task_name: Task name for pre train task, i.e., sending initial model weights.
        """
        super().__init__()

        self._lr = lr
        self._epochs = epochs
        self._train_task_name = train_task_name
        self._pre_train_task_name = pre_train_task_name
        self._submit_model_task_name = submit_model_task_name
        self._exclude_vars = exclude_vars

        # Training setup
        self.model = MnistNet()
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device)
        self.loss = nn.CrossEntropyLoss()
        self.optimizer = SGD(self.model.parameters(), lr=lr)

        # Create Cifar10 dataset for training.
        transforms = Compose(
            [
                ToTensor(),
                # Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)),
            ]
        )
        raw_train_dataset = FashionMNIST(root=data_path, transform=transforms, download=True, train=True)
        self._train_dataset = torch.utils.data.Subset(raw_train_dataset, range(SUBSET_SIZE))

        self._train_loader = DataLoader(self._train_dataset, batch_size=4, shuffle=True)
        self._n_iterations = len(self._train_loader)

        # Setup the persistence manager to save PT model.
        # The default training configuration is used by persistence manager
        # in case no initial model is found.
        self._default_train_conf = {"train": {"model": type(self.model).__name__}}
        self.persistence_manager = PTModelPersistenceFormatManager(
            data=self.model.state_dict(), default_train_conf=self._default_train_conf
        )

    def execute(self, task_name: str, shareable: Shareable, fl_ctx: FLContext, abort_signal: Signal) -> Shareable:
        try:
            if task_name == self._pre_train_task_name:
                # Get the new state dict and send as weights
                return self._get_model_weights()
            elif task_name == self._train_task_name:
                # Get model weights
                try:
                    dxo = from_shareable(shareable)
                except:
                    self.log_error(fl_ctx, "Unable to extract dxo from shareable.")
                    return make_reply(ReturnCode.BAD_TASK_DATA)

                # Ensure data kind is weights.
                if not dxo.data_kind == DataKind.WEIGHTS:
                    self.log_error(fl_ctx, f"data_kind expected WEIGHTS but got {dxo.data_kind} instead.")
                    return make_reply(ReturnCode.BAD_TASK_DATA)

                # Convert weights to tensor. Run training
                torch_weights = {k: torch.as_tensor(v) for k, v in dxo.data.items()}
                self._local_train(fl_ctx, torch_weights, abort_signal)

                # Check the abort_signal after training.
                # local_train returns early if abort_signal is triggered.
                if abort_signal.triggered:
                    return make_reply(ReturnCode.TASK_ABORTED)

                # Save the local model after training.
                self._save_local_model(fl_ctx)

                # Get the new state dict and send as weights
                return self._get_model_weights()
            elif task_name == self._submit_model_task_name:
                # Load local model
                ml = self._load_local_model(fl_ctx)

                # Get the model parameters and create dxo from it
                dxo = model_learnable_to_dxo(ml)
                return dxo.to_shareable()
            else:
                return make_reply(ReturnCode.TASK_UNKNOWN)
        except Exception as e:
            self.log_exception(fl_ctx, f"Exception in simple trainer: {e}.")
            return make_reply(ReturnCode.EXECUTION_EXCEPTION)

    def _get_model_weights(self) -> Shareable:
        # Get the new state dict and send as weights
        weights = {k: v.cpu().numpy() for k, v in self.model.state_dict().items()}

        outgoing_dxo = DXO(
            data_kind=DataKind.WEIGHTS, data=weights, meta={MetaKey.NUM_STEPS_CURRENT_ROUND: self._n_iterations}
        )
        return outgoing_dxo.to_shareable()

    def _local_train(self, fl_ctx, weights, abort_signal):
        torch.set_num_threads(1)
        # Set the model weights
        self.model.load_state_dict(state_dict=weights)

        batch_size = BATCH_SIZE
        num_parties = NUM_PARTIES

        train_dataset = self._train_dataset
        train_dataset_size = len(train_dataset)
        train_dataset_subset = train_dataset_size // num_parties
        identity_name = fl_ctx.get_identity_name()

        site_n = identity_name.split("-")[-1]
        if site_n.isdigit():
            site_n = int(site_n)
        else:
            self.log_info(fl_ctx, f"Invalid site number in identity name.")

        train_data_range = range(train_dataset_subset * (site_n - 1), train_dataset_subset * site_n)

        train_dataset_subset = torch.utils.data.Subset(train_dataset, train_data_range)
        self.log_info(fl_ctx, f"{identity_name} training on first {len(train_dataset_subset)} samples.")

        # if identity_name == "site-1":
        #     train_dataset_subset = torch.utils.data.Subset(train_dataset, range(train_dataset_subset))
        #     self.log_info(fl_ctx, f"{identity_name} training on first {len(train_dataset_subset)} samples.")
        # elif identity_name == "site-2":
        #     train_dataset_subset = torch.utils.data.Subset(train_dataset, range(train_dataset_subset, train_dataset_subset * 2))
        #     self.log_info(fl_ctx, f"{identity_name} training on second {len(train_dataset_subset)} samples.")
        # elif identity_name == "site-3":
        #     train_dataset_subset = torch.utils.data.Subset(train_dataset, range(train_dataset_subset * 2, train_dataset_subset * 3))
        #     self.log_info(fl_ctx, f"{identity_name} training on second {len(train_dataset_subset)} samples.")
        # else:
        #     train_dataset_subset = torch.utils.data.Subset(train_dataset, range(train_dataset_subset * 3, train_dataset_subset * 4))
        #     self.log_info(fl_ctx, f"{identity_name} training on last {len(train_dataset_subset)} samples.")

        train_dataset_subset_loader = DataLoader(train_dataset_subset, batch_size=batch_size, shuffle=True)
        # Basic training
        self.model.train()
        for epoch in range(self._epochs):
            running_loss = 0.0
            epoch_start = time.perf_counter()
            for i, batch in enumerate(train_dataset_subset_loader):
                if abort_signal.triggered:
                    # If abort_signal is triggered, we simply return.
                    # The outside function will check it again and decide steps to take.
                    return

                images, labels = batch[0].to(self.device), batch[1].to(self.device)
                self.optimizer.zero_grad()

                predictions = self.model(images)
                cost = self.loss(predictions, labels)
                cost.backward()
                self.optimizer.step()

                running_loss += cost.cpu().detach().numpy() / images.size()[0]
                if i % 3000 == 0:
                    self.log_info(
                        fl_ctx, f"Epoch: {epoch}/{self._epochs}, Iteration: {i}, " f"Loss: {running_loss/3000}"
                    )
                    running_loss = 0.0
            epoch_end = time.perf_counter()
            epoch_duration = epoch_end - epoch_start
            with open("datasize_mnist_nn.csv", "a") as fp:
                wr = csv.writer(fp, dialect='excel')
                # epoch_duration, epoch, batch_size, data_size, accuracy, test_duration
                wr.writerow([epoch_duration, EPOCH_NUM, batch_size, train_dataset_size])


    def _save_local_model(self, fl_ctx: FLContext):
        run_dir = fl_ctx.get_engine().get_workspace().get_run_dir(fl_ctx.get_prop(ReservedKey.RUN_NUM))
        models_dir = os.path.join(run_dir, PTConstants.PTModelsDir)
        if not os.path.exists(models_dir):
            os.makedirs(models_dir)
        model_path = os.path.join(models_dir, PTConstants.PTLocalModelName)

        ml = make_model_learnable(self.model.state_dict(), {})
        self.persistence_manager.update(ml)
        torch.save(self.persistence_manager.to_persistence_dict(), model_path)

    def _load_local_model(self, fl_ctx: FLContext):
        run_dir = fl_ctx.get_engine().get_workspace().get_run_dir(fl_ctx.get_prop(ReservedKey.RUN_NUM))
        models_dir = os.path.join(run_dir, PTConstants.PTModelsDir)
        if not os.path.exists(models_dir):
            return None
        model_path = os.path.join(models_dir, PTConstants.PTLocalModelName)

        self.persistence_manager = PTModelPersistenceFormatManager(
            data=torch.load(model_path), default_train_conf=self._default_train_conf
        )
        ml = self.persistence_manager.to_model_learnable(exclude_vars=self._exclude_vars)
        return ml
