import os
import sys
import logging

logger = logging.getLogger("live_trade")

def get_executable_directory():
    try:
        if getattr(sys, 'frozen', False):
            executable_path = sys.executable
        else:
            executable_path = os.path.abspath(__file__)
        directory_path = executable_path
        logger.info(f"Duong dan thu muc: {directory_path}")
        return directory_path
    except Exception as e:
        logger.error(f"loi khi khon the thuc thi: {e}")
        return None

path_directory = os.path.dirname(get_executable_directory())
current_dir_results = os.path.join(path_directory, 'results')
current_dir_models = os.path.join(path_directory, 'models')
current_dir_backtest = os.path.join(current_dir_results, 'backtest')



