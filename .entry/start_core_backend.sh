#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

nginx -g 'daemon off;' &
gunicorn -c .config/gunicorn_config.py farajayangu_be.asgi -k uvicorn.workers.UvicornWorker
