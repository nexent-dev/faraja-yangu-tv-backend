#!/bin/bash

# Ensure timezone is correctly set
export TZ=Africa/Dar_es_Salaam

# Start Celery worker in background
celery -A farajayangu_be.celery worker -l info --pool=threads -E &
WORKER_PID=$!

# Start Celery beat scheduler in background
celery -A farajayangu_be beat -l INFO --scheduler django_celery_beat.schedulers:DatabaseScheduler &
BEAT_PID=$!

echo "Celery Worker started with PID: $WORKER_PID"
echo "Celery Beat started with PID: $BEAT_PID"

# Wait for both processes (keeps container running)
wait $WORKER_PID $BEAT_PID
