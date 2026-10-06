module.exports = {
  apps: [
    {
      name: "komdigi-bot-worker",
      script: "python3",
      args: "start_service.py --host 0.0.0.0 --port 8080",
      cwd: "/home/ubuntu/apps/komdigi-bot",
      interpreter: "/home/ubuntu/apps/komdigi-bot/.venv/bin/python",
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
        PYTHONPATH: "src",
      },
    },
  ],
};
