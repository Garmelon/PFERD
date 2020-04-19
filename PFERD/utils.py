import os
import sys
import pathlib
from colorama import Style
from colorama import Fore

def move(path, from_folders, to_folders):
    l = len(from_folders)
    if path.parts[:l] == from_folders:
        return pathlib.PurePath(*to_folders, *path.parts[l:])

def rename(path, to_name):
    return pathlib.PurePath(*path.parts[:-1], to_name)

def stream_to_path(response, to_path, chunk_size=1024**2):
    with open(to_path, 'wb') as fd:
        for chunk in response.iter_content(chunk_size=chunk_size):
            fd.write(chunk)

class PrettyLogger:

    def __init__(self, logger):
        self.logger = logger

    def modified_file(self, file_name):
        self.logger.info(f"{Fore.MAGENTA}{Style.BRIGHT}Modified {file_name}.{Style.RESET_ALL}")

    def new_file(self, file_name):
        self.logger.info(f"{Fore.GREEN}{Style.BRIGHT}Created {file_name}.{Style.RESET_ALL}")

    def ignored_file(self, file_name):
        self.logger.info(f"{Style.DIM}Ignored {file_name}.{Style.RESET_ALL}")

    def starting_synchronizer(self, target_directory, synchronizer_name, subject=None):
        subject_str = f"{subject} " if subject else ""
        self.logger.info("")
        self.logger.info((
            f"{Fore.CYAN}{Style.BRIGHT}Synchronizing {subject_str}to {target_directory}"
            f" using the {synchronizer_name} synchronizer.{Style.RESET_ALL}"
        ))
