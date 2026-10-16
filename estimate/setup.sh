#!/usr/bin/env bash
# 在租来的 GPU 服务器上运行一次：安装依赖，并把 Hugging Face 缓存放到持久化的 Volume 上
set -euo pipefail

export HF_HOME=${HF_HOME:-/workspace/hf}
mkdir -p "$HF_HOME"
grep -q "HF_HOME" ~/.bashrc || echo "export HF_HOME=$HF_HOME" >> ~/.bashrc

nvidia-smi
pip install -U pip
pip install -r requirements.txt

python - <<'EOF'
import torch, vllm
print("torch", torch.__version__, "| CUDA 可用:", torch.cuda.is_available(), "| vLLM", vllm.__version__)
print("GPU:", torch.cuda.get_device_name(0))
EOF

# 提前下载模型（约 20 GB），之后启动更快
python -c "from huggingface_hub import snapshot_download; snapshot_download('Qwen/Qwen2.5-32B-Instruct-AWQ')"
echo "准备好了。下一步：tmux new -s m2，然后按 README 第 2 步运行 estimate.py"
