server {
    listen 80;
    server_name farajayangutv.co.tz;

    location /media/ {
        # proxy_pass http://0.0.0.0:8000/media/;
        alias /app/media/;
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;
        # sendfile on;
        # try_files /$1 =404;
        # autoindex on;
        # root  /;
    }

    location / {
        proxy_pass http://0.0.0.0:8000;
    }
}