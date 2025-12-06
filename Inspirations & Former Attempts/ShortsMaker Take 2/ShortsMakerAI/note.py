import torch
print(f"PyTorch version: {torch.__version__}")
print(f"CUDA available: {torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"  CUDA device count: {torch.cuda.device_count()}")
    print(f"  Current CUDA device index: {torch.cuda.current_device()}")
    print(f"  Device name: {torch.cuda.get_device_name(0)}")
else:
    print("  CUDA is NOT available to PyTorch. This is likely the root of the float16 issue.")
    print("  Ensure NVIDIA drivers are correctly installed and that your PyTorch version supports your CUDA driver version.")
