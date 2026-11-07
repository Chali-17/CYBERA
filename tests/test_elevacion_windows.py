"""Pruebas del arranque con elevación a administrador (habilitador del motor ARP)."""

from __future__ import annotations

import sys

import pytest

import infrastructure.elevacion_windows as elevacion


def test_es_administrador_devuelve_bool():
    assert isinstance(elevacion.es_administrador(), bool)


def test_solicitar_elevacion_fuera_de_windows_no_eleva(monkeypatch):
    monkeypatch.setattr(elevacion.sys, "platform", "linux")
    assert elevacion.solicitar_elevacion() is False


def test_solicitar_elevacion_con_administrador_verificado_no_eleva(monkeypatch):
    monkeypatch.setattr(elevacion.sys, "platform", "win32")
    monkeypatch.setattr(elevacion, "es_administrador", lambda: True)
    assert elevacion.solicitar_elevacion() is True


def test_solicitar_elevacion_sin_admin_y_sin_shell_ejecutable_no_eleva(monkeypatch):
    monkeypatch.setattr(elevacion.sys, "platform", "win32")
    monkeypatch.setattr(elevacion, "es_administrador", lambda: False)
    monkeypatch.setattr(elevacion, "_ejecutar_shell_ejecutable", lambda archivo, parametros: False)
    assert elevacion.solicitar_elevacion() is False


def test_solicitar_elevacion_sin_admin_pide_elevacion(monkeypatch):
    monkeypatch.setattr(elevacion.sys, "platform", "win32")
    monkeypatch.setattr(elevacion, "es_administrador", lambda: False)
    monkeypatch.setattr(elevacion, "_ejecutar_shell_ejecutable",
                        lambda archivo, parametros: True)
    assert elevacion.solicitar_elevacion() is True
