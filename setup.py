from setuptools import find_packages, setup

setup(
    name="PFERD",
    version="2.6.2",
    packages=find_packages(),
    install_requires=[
        "httpx>=0.17.1",
        "beautifulsoup4>=4.7.1",
        "rich>=2.1.0",
        "keyring>=21.5.0"
    ],
)

# When updating the version, also:
# - update the README.md installation instructions
# - set a tag on the update commit
