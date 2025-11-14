import multiprocessing

command='gunicorn'
pythonpath='/app'
bind='0.0.0.0:8000'
workers=4

worker_class = 'uvicorn.workers.UvicornH11Worker'