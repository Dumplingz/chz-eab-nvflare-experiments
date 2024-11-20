import os
import pandas as pd

if __name__ == '__main__':
    # Create experiments directory
    os.makedirs('fl-nn/experiments/mnist', exist_ok=True)
    os.makedirs('fl-nn/experiments/cifar', exist_ok=True)
    
    
    
    base_dir = "/tmp/nvflare/poc/example_project/prod_00"
    
    files = [
        "datasize_cifar_nn.csv",
        # "datasize_cifar_nn_validation.csv",
        "datasize_mnist_nn.csv",
        # "datasize_mnist_nn_validation.csv"
    ]

    sites = ["site-1", "site-2", "site-3", "site-4"]

    for file in files:
        combined_df = pd.DataFrame()
        for site in sites:
            file_path = os.path.join(base_dir, site, file)
            if os.path.exists(file_path):
                df = pd.read_csv(file_path, header=None)
                df['site'] = site
                combined_df = pd.concat([combined_df, df], ignore_index=True)
        combined_df.to_csv(f'experiments/{file}', index=False, header=False)