# -*- coding: utf-8 -*-
"""JSON 状态存储：读-改-写，带原子替换，避免半截文件。"""
import json
import os
import tempfile
import threading

_LOCK = threading.Lock()


class Store(object):
    def __init__(self, path):
        self.path = path
        self._data = {}
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
            except (ValueError, OSError):
                self._data = {}
        return self._data

    def get(self, key, default=None):
        with _LOCK:
            return self._data.get(key, default)

    def set(self, key, value):
        with _LOCK:
            self._data[key] = value
            self._flush()

    def update(self, **kw):
        with _LOCK:
            self._data.update(kw)
            self._flush()

    def _flush(self):
        d = os.path.dirname(self.path)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        fd, tmp = tempfile.mkstemp(dir=d or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
