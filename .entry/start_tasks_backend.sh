#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

celery -A farajayangu_be.celery worker -l info --pool=threads -E &
celery -A farajayangu_be beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler
