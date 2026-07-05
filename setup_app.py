from setuptools import setup

APP = ['unified_sync.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'LSUIElement': True,
        'CFBundleName': 'Nothing AirShare',
        'CFBundleDisplayName': 'Nothing AirShare',
        'CFBundleIdentifier': "com.nothing.airshare.mac",
        'CFBundleVersion': "2.9.0",
        'CFBundleShortVersionString': "2.9.0",
    }
}

setup(
    app=APP,
    name='Nothing AirShare',
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
