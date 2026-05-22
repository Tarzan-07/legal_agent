# import cupy
# import thinc
# import spacy

# # 1. Verify if CuPy can actually see your NVIDIA graphics card
# print("CuPy GPU Available:", cupy.cuda.is_available())

# # 2. Check if spaCy can successfully switch its backend array over to the GPU
# print("spaCy GPU Allocated:", spacy.prefer_gpu())


import torch

print(torch.__version__)
print(torch.version.cuda)