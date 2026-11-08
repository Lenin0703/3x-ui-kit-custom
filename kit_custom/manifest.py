"""Pinned, independently verified public upstream artifacts.

The KIT scripts are pinned by their Git blob SHA-1 (their immutable Git content IDs).
The official x-ui installer and binary archives are additionally pinned by SHA-256.
Hashes and version changes require a reviewed release of this project.
"""

KIT_TAG = 'v1.2.1'
PANEL_VERSION = 'v3.9.0'
XRAY_PIN = 'v26.6.27'  # retained by the upstream KIT; do not update automatically

KIT_FILES = {
    '3x-ui.sh': {
        'path': 'scripts/3x-ui.sh',
        'blob': 'dcedf2490ca04475fe4d4f231a1afea3beabfef6',
    },
    'kit.sh': {
        'path': 'scripts/kit.sh',
        'blob': 'e05520373b3b1d80b4a4eeb030f734a07b9b166b',
    },
    'kit-sub.py': {
        'path': 'scripts/kit-sub.py',
        'blob': 'f62460da4eb1dd2a060e8e04918657eda1c582d7',
    },
}

PANEL_INSTALL_BLOB = 'bd8945f92a35799df18f8205cbc3e0ce294f5ebb'
PANEL_INSTALL_SHA256 = '18616fe26c8f6c92db6daa2dcd7cd53c5143ee69ecfd26d8ea6dc9b2c78607a6'
PANEL_ARCHIVES = {
    'amd64': 'd7cbe0bf6358ee0d2117c24fd2efb483502e411d38e2ea59bd0bf5e7a3e39390',
    'arm64': '9a2e43c976a2e71618a30d8f38b52476b25ed363c6989599e2f625cc52f51a81',
}

# Discoverable releases != certified compatible with the KIT's pinned Xray/schema.
VERSION_STATUS = {
    'v3.9.0': 'ПРОВЕРЕНО: закреплена в KIT v1.2.1; поддержана установщиком Custom',
    'v3.10.0': 'НЕ ПРОВЕРЕНО: блокируем установку до тестов совместимости',
    'v3.10.2': 'НЕ ПРОВЕРЕНО: блокируем установку до тестов совместимости',
    'v3.11.0': 'НЕ ПРОВЕРЕНО: блокируем установку до тестов совместимости',
}
