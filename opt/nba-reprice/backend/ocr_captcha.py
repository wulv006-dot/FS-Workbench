#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""识别验证码图片，输出识别结果。用法: python ocr_captcha.py <图片路径>"""
import sys
import ddddocr

def main():
    img_path = sys.argv[1]
    ocr = ddddocr.DdddOcr(show_ad=False)
    with open(img_path, 'rb') as f:
        img_bytes = f.read()
    result = ocr.classification(img_bytes)
    # ddddocr 默认可能带概率，取第一个结果
    print(result)

if __name__ == '__main__':
    main()
