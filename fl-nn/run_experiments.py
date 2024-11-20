import os
import sys
import csv
from nvflare.fuel.flare_api.flare_api import new_secure_session, Session
import json
import pandas as pd

def format_json( data: dict): 
    print(json.dumps(data, sort_keys=True, indent=4,separators=(',', ': ')))

def sample_cb(
        session: Session, job_id: str, job_meta, *cb_args, **cb_kwargs
    ) -> bool:
    if job_meta["status"] == "RUNNING":
        if cb_kwargs["cb_run_counter"]["count"] < 3:
            print(job_meta)
            print(cb_kwargs["cb_run_counter"])
        else:
            print(".", end="")
    else:
        print("\n" + str(job_meta))
    
    cb_kwargs["cb_run_counter"]["count"] += 1
    return True

if __name__ == '__main__':
    num_trials = int(sys.argv[1])

    model = str(sys.argv[2])
    
    trial = str(sys.argv[3])
    
    if model != "cifar" and model != "mnist":
        print(f"Model must be cifar or mnist. Got {model}")
        exit(1)

    if trial is None:
        print("Trial details must be provided")
        exit(1)
        
    trial_dir = f"experiments/{model}/{trial}"
    
    # create experiment dir
    os.makedirs(trial_dir, exist_ok=True)
    
    username = "admin@nvidia.com"
    admin_user_dir = os.path.join("/tmp/nvflare/poc/example_project/prod_00", username)
    sess = new_secure_session(
        username=username,
        startup_kit_location=admin_user_dir
    )
    # print(sess.get_system_info())
    # job_id = "ef6e1646-7699-455d-8586-9d7957b0bafc"

    # print(sess.download_job_result(job_id))
    
    # exit(0)

    # get job dir from full path
    cwd = os.getcwd()
    job_dir = os.path.join(cwd, f"jobs/nvflare_nn_{model}")
    
    for i in range(num_trials):
        # submit and get job info
        job_id = sess.submit_job(job_dir)

        print(sess.get_job_meta(job_id))

        # wait until job is done
        sess.monitor_job(job_id, cb=sample_cb, cb_run_counter={"count":0})

        list_jobs_output = sess.list_jobs()
        for job in list_jobs_output:
            if job_id == job["job_id"]:
                print("Found job")
                print(job)

                # get duration in seconds
                duration_parts = job["duration"].split(":")
                seconds = int(duration_parts[0]) * 3600 + int(duration_parts[1]) * 60 + float(duration_parts[2])
                print(f"Duration in seconds: {seconds}")
                
                with open(f"{trial_dir}/total_time.csv", "a") as fp:
                    wr = csv.writer(fp, dialect='excel')
                    # epoch_duration, epoch, batch_size, data_size, accuracy, test_duration
                    wr.writerow([seconds, job_id, job["submit_time"]])

                break
    
    base_dir = "/tmp/nvflare/poc/example_project/prod_00"
    
    file = f"datasize_{model}_nn.csv"

    sites = ["site-1", "site-2", "site-3", "site-4"]

    combined_df = pd.DataFrame()
    for site in sites:
        file_path = os.path.join(base_dir, site, file)
        if os.path.exists(file_path):
            df = pd.read_csv(file_path, header=None)
            df['site'] = site
            combined_df = pd.concat([combined_df, df], ignore_index=True)
            # remove for next trials
            os.remove(file_path)
    combined_df.to_csv(f'{trial_dir}/{file}', index=False, header=False)
    print("Job done running. Change the params for a new experiment!")
        # print(list_jobs_output)
        # print(format_json(list_jobs_output))