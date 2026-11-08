# Shared by both apps in deploy/nginx-web.conf.
# nginx drops inherited add_header lines in any location that adds its own, so each location repeats them.
client_max_body_size 10m;
server_tokens off;

location ~ ^/(api|django-admin|static)/ {
    # Set by each server: production's backend, or the training copy's (D-290).
    proxy_pass http://$frutti_api;
    proxy_set_header Host $http_host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $forwarded_proto;
    proxy_read_timeout 60s;
}

# Built files have a hash in their name: cache them for a year.
location /assets/ {
    add_header Cache-Control "public, immutable" always;
    add_header X-Content-Type-Options nosniff always;
    expires 1y;
    try_files $uri =404;
}

# Every other path is a screen of the app: always fetch a fresh index.html so a deploy shows at once.
location / {
    add_header Cache-Control "no-cache" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy same-origin always;
    add_header X-Frame-Options DENY always;
    try_files $uri /index.html;
}
