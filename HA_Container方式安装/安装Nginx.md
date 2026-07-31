# 安装Nginx

## 修改Nginx目录权限
```shell
sudo mkdir -p /home/HA/nginx/conf.d
sudo mkdir -p /home/HA/nginx/certs
sudo chown -R HA:HA /home/HA/nginx
```

## 编写Nginx配置文件
```shell
sudo vim /home/HA/nginx/conf.d/default.conf
```
```text
server {
    listen 80;
    server_name x.x.x.x;  # 替换为你的域名或IP地址，空格隔开可填多个

    # 所有代理通用设置
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    location / {
        proxy_pass http://127.0.0.1:8123;
    }

    location /esphome/ {
        proxy_pass http://127.0.0.1:6052/;
        # 如果直接访问端口可访问，但是访问路径无法访问，可以尝试取消下方注释
        # sub_filter '<base href="/">' '<base href="/esphome/">';
        # sub_filter_once on;
    }

    location /nodered/ {
        proxy_pass http://127.0.0.1:1880/;
    }
}
```

## 拉取Nginx镜像
```shell
sudo docker pull nginx
```

## 更新compose.yaml文件内容
追加以下内容
```yaml
  nginx:
    container_name: nginx
    image: "nginx:latest"
    volumes:
      - /home/HA/nginx/conf.d:/etc/nginx/conf.d
      # - /home/HA/nginx/certs:/etc/nginx/certs  # 如果使用HTTPS请取消注释并正确配置证书
    restart: unless-stopped
    network_mode: host  # 使用host模式
    user: root
```

## 启动Nginx
```shell
sudo docker compose up -d
```

## 更新HA中ESPHome和Node-RED的链接
ESPHome的链接设为`/esphome/`，不要有任何其他内容。Node-RED同理设为`/nodered`