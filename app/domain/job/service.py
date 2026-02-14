from app.domain.job import repository as job_repo


def create_job(job_doc):
    return job_repo.save_job(job_doc)


def get_job(job_id: str):
    return job_repo.find_job(job_id)
