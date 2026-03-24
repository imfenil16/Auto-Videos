import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8080')}"
workers = 1
timeout = 600          # 10 min — video rendering is slow
graceful_timeout = 600
keepalive = 5
