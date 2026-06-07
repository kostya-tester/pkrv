#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты подключения к стендам.
Запуск: python -m pytest tests/ -v
или:    python tests/test_connection.py
"""

import sys
import os
import socket
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Список стендов (должен совпадать с main.py)
STANDS = {
    "ГОЗ":     {"ip": "192.168.243.248", "port": 22},
    "Арктика": {"ip": "192.168.243.249", "port": 22},
    "C1M":     {"ip": "192.168.243.254", "port": 22},
    "OrangePi":{"ip": "192.168.243.46",  "port": 22},
}

TIMEOUT = 3  # секунды


def check_port(ip, port, timeout=TIMEOUT):
    """Проверка доступности порта."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, port))
        s.close()
        return result == 0
    except Exception as e:
        return False


def check_ssh_auth(ip, port, username, password, timeout=TIMEOUT):
    """Проверка SSH авторизации через Paramiko."""
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=ip, port=port,
            username=username, password=password,
            timeout=timeout, allow_agent=False, look_for_keys=False
        )
        ssh.close()
        return True, "OK"
    except paramiko.AuthenticationException:
        return False, "Неверный логин или пароль"
    except paramiko.SSHException as e:
        return False, f"SSH ошибка: {e}"
    except socket.timeout:
        return False, "Таймаут подключения"
    except Exception as e:
        return False, f"Ошибка: {e}"


class TestStandAvailability(unittest.TestCase):
    """Проверка сетевой доступности стендов."""

    def _check_stand(self, name, ip, port):
        available = check_port(ip, port)
        self.assertTrue(
            available,
            f"\n{'='*50}\n"
            f"❌ Стенд недоступен: {name}\n"
            f"   IP:   {ip}\n"
            f"   Порт: {port}\n"
            f"   Причина: не вижу стенд в сети\n"
            f"   Проверьте:\n"
            f"     1. Стенд включён?\n"
            f"     2. Сетевой кабель подключён?\n"
            f"     3. Правильный IP в конфиге?\n"
            f"{'='*50}"
        )

    def test_goz_available(self):
        """ГОЗ доступен по сети"""
        s = STANDS["ГОЗ"]
        self._check_stand("ГОЗ", s["ip"], s["port"])

    def test_arktika_available(self):
        """Арктика доступна по сети"""
        s = STANDS["Арктика"]
        self._check_stand("Арктика", s["ip"], s["port"])

    def test_c1m_available(self):
        """C1M доступен по сети"""
        s = STANDS["C1M"]
        self._check_stand("C1M", s["ip"], s["port"])

    def test_orangepi_available(self):
        """OrangePi доступен по сети"""
        s = STANDS["OrangePi"]
        self._check_stand("OrangePi", s["ip"], s["port"])


class TestParamiko(unittest.TestCase):
    """Проверка что paramiko установлен."""

    def test_paramiko_installed(self):
        """Paramiko установлен"""
        try:
            import paramiko
        except ImportError:
            self.fail(
                "\n❌ Paramiko не установлен!\n"
                "   Установите: pip install paramiko\n"
            )


class TestSSHConnection(unittest.TestCase):
    """Проверка SSH подключения к стендам."""

    CREDENTIALS = {
        "ГОЗ":      {"username": "pkrv", "password": "zxcv"},
        "Арктика":  {"username": "pkrv", "password": "zxcv"},
        "C1M":      {"username": "pkrv", "password": "zxcv"},
        "OrangePi": {"username": "orangepi", "password": ""},
    }

    def _check_ssh(self, name):
        s = STANDS[name]
        c = self.CREDENTIALS[name]

        # Сначала проверяем сеть
        if not check_port(s["ip"], s["port"]):
            self.skipTest(
                f"Стенд {name} недоступен по сети — пропускаем SSH тест"
            )

        ok, msg = check_ssh_auth(s["ip"], s["port"], c["username"], c["password"])
        self.assertTrue(
            ok,
            f"\n{'='*50}\n"
            f"❌ SSH подключение не удалось: {name}\n"
            f"   IP:       {s['ip']}\n"
            f"   Порт:     {s['port']}\n"
            f"   Пользователь: {c['username']}\n"
            f"   Причина:  {msg}\n"
            f"   Проверьте:\n"
            f"     1. Правильный пароль в конфиге?\n"
            f"     2. SSH сервис запущен на стенде?\n"
            f"     3. Пользователь {c['username']} существует?\n"
            f"{'='*50}"
        )

    def test_goz_ssh(self):
        """SSH подключение к ГОЗ"""
        self._check_ssh("ГОЗ")

    def test_arktika_ssh(self):
        """SSH подключение к Арктике"""
        self._check_ssh("Арктика")

    def test_c1m_ssh(self):
        """SSH подключение к C1M"""
        self._check_ssh("C1M")

    def test_orangepi_ssh(self):
        """SSH подключение к OrangePi"""
        self._check_ssh("OrangePi")


if __name__ == "__main__":
    print("=" * 50)
    print("Диагностика стендов")
    print("=" * 50)

    all_ok = True
    for name, cfg in STANDS.items():
        ip, port = cfg["ip"], cfg["port"]
        available = check_port(ip, port)
        status = "✅ ONLINE " if available else "❌ OFFLINE"
        print(f"  {status} | {name:10} | {ip}:{port}")
        if not available:
            all_ok = False
            print(f"           Причина: не вижу стенд в сети")
            print(f"           Проверьте: питание, кабель, IP")

    print("=" * 50)
    if all_ok:
        print("Все стенды доступны ✅")
    else:
        print("Некоторые стенды недоступны ❌")
        print("Запустите pytest для подробного отчёта:")
        print("  python -m pytest tests/ -v")
