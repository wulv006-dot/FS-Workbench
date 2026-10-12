# 服务端「直连改价后台」执行镜像
# ---------------------------------------------------------------------------
# 目的：让服务器自己就能登录 order.p2pah.cn（图形验证码 → 本地离线 OCR）、
#       读价、发写请求 —— 不再依赖本机执行器。
#
# 为什么直接叠在 qd-render 上：
#   qd-render:1.47 已经把 playwright 1.47.0 的 Python 包和 chromium-1134 装好了
#   （官方 playwright 镜像里反而**没有** Python 包，只有浏览器）。
#   这里只补 OCR 所需的 ddddocr / pillow / numpy，省掉 2GB 的重装。
#
# 2026-09-27 建。
FROM qd-render:1.47

# ddddocr 依赖 onnxruntime + opencv-python-headless + pillow + numpy。
# ⚠ numpy 不锁版本时会被拉到 2.x，老 onnxruntime 会报 "_ARRAY_API not found"；
#    这里显式压住 numpy<2，避免运行期才炸。
RUN pip install --no-cache-dir "numpy<2" "pillow" "ddddocr==1.5.6" \
 && python -c "\
import numpy, PIL, onnxruntime, ddddocr, playwright;\
print('[build] numpy', numpy.__version__);\
print('[build] onnxruntime', onnxruntime.__version__);\
print('[build] ddddocr ok');\
print('[build] playwright chromium ready')"
