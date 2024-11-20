import os
import sys
import csv
from nvflare.fuel.flare_api.flare_api import new_secure_session, Session
import json

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
    
    # create experiment dir
    os.makedirs('experiments', exist_ok=True)
    
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
    job_dir = os.path.join(cwd, "jobs/nvflare_nn_cifar")
    
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
                
                with open("experiments/cifar_total_time.csv", "a") as fp:
                    wr = csv.writer(fp, dialect='excel')
                    # epoch_duration, epoch, batch_size, data_size, accuracy, test_duration
                    wr.writerow([seconds, job_id, job["submit_time"]])

                break
    
    print("Job done running. Change the params for a new experiment!")
        # print(list_jobs_output)
        # print(format_json(list_jobs_output))