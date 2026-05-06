from math import sqrt

def calc_log_window(center_freq, window_size):
    lower_freq = (-window_size + sqrt(window_size**2 + 4 * center_freq**2)) / 2
    upper_freq = (lower_freq + window_size)
    return int(lower_freq), int(upper_freq)

def calc_floor(center_freq, ceil_freq):
    floor_freq = center_freq**2 / ceil_freq
    return int(floor_freq)