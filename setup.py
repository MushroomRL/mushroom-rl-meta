from setuptools import setup, find_packages
from codecs import open
from os import path

from mushroom_rl_meta import __version__

here = path.abspath(path.dirname(__file__))

requires_list = []
with open(path.join(here, 'requirements.txt'), encoding='utf-8') as f:
    for line in f:
        requires_list.append(str(line))

long_description = 'MushroomRL Meta is a Python Reinforcement Learning (RL) library' \
                   ' extending MushroomRL, allowing the user to perform multitask' \
                   ' and Meta  RL'

setup(
    name='mushroom-rl-meta',
    version=__version__,
    description='A Python library for Multitask and Meta Reinforcement Learning experiments.',
    long_description=long_description,
    url='https://github.com/MushroomRL/mushroom-rl-meta',
    author="Carlo D'Eramo, Davide Tateo",
    author_email='carlo.deramo@gmail.com',
    license='MIT',
    packages=[package for package in find_packages()
              if package.startswith('mushroom_rl_meta')],
    zip_safe=False,
    install_requires=requires_list,
    classifiers=["Programming Language :: Python :: 3",
                 "License :: OSI Approved :: MIT License",
                 "Operating System :: OS Independent",
                 ]
)
