#!/usr/bin/env bash
# 在租来的 GPU 服务器上运行一次：安装依赖，并把 Hugging Face 缓存放到持久化的存储上
# Lambda：先建好放在文件系统上的 venv，再运行
#   python3 -m venv /lambda/nfs/<fs>/venv && source /lambda/nfs/<fs>/venv/bin/activate
#   HF_HOME=/lambda/nfs/<fs>/hf bash setup.sh
# 实例的本地硬盘在 Terminate 时会被清空，环境和模型都要放在文件系统上
set -euo pipefail

if [ -z "${HF_HOME:-}" ]; then
  for d in /lambda/nfs/*; do [ -d "$d" ] && HF_HOME="$d/hf" && break; done
fi
export HF_HOME=${HF_HOME:-$HOME/hf}
mkdir -p "$HF_HOME"
echo "HF_HOME=$HF_HOME"
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
