from unittest.mock import MagicMock
import sys
import pytest

from andro_cfw import patch, CFWSession, WorkerEntry


def test_patch_telebot(monkeypatch):
    mock_session = CFWSession(
        worker_name="test-worker",
        worker_url="https://test.workers.dev",
        workers=[WorkerEntry("test-worker", "https://test.workers.dev", "acc1")],
    )

    mock_telebot = MagicMock()
    mock_telebot.apihelper = MagicMock()
    monkeypatch.setitem(sys.modules, "telebot", mock_telebot)

    res = patch(mock_session)
    assert res is mock_session
    assert mock_telebot.apihelper.API_URL == "https://test.workers.dev/bot{0}/{1}"
    assert mock_telebot.apihelper.FILE_URL == "https://test.workers.dev/file/bot{0}/{1}"


def test_patch_pyrogram(monkeypatch):
    mock_session = CFWSession(
        worker_name="test-worker",
        worker_url="https://test.workers.dev",
        workers=[WorkerEntry("test-worker", "https://test.workers.dev", "acc1")],
    )

    mock_pyrogram = MagicMock()
    mock_pyrogram.Client = MagicMock()
    monkeypatch.setitem(sys.modules, "pyrogram", mock_pyrogram)

    res = patch(mock_session)
    assert res is mock_session
    assert mock_pyrogram.Client.api_url == "https://test.workers.dev"


def test_patch_aiogram(monkeypatch):
    mock_session = CFWSession(
        worker_name="test-worker",
        worker_url="https://test.workers.dev",
        workers=[WorkerEntry("test-worker", "https://test.workers.dev", "acc1")],
    )

    mock_aiogram = MagicMock()
    monkeypatch.setitem(sys.modules, "aiogram", mock_aiogram)

    res = patch(mock_session)
    assert res is mock_session
    assert mock_aiogram.client.telegram.TelegramAPIServer.from_base.called


def test_patch_telegram(monkeypatch):
    mock_session = CFWSession(
        worker_name="test-worker",
        worker_url="https://test.workers.dev",
        workers=[WorkerEntry("test-worker", "https://test.workers.dev", "acc1")],
    )

    mock_telegram = MagicMock()
    monkeypatch.setitem(sys.modules, "telegram", mock_telegram)

    res = patch(mock_session)
    assert res is mock_session
    assert mock_telegram.Bot._base_url == "https://test.workers.dev"
