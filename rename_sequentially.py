import glob
import shutil
files = glob.glob("source/*.jpg")

filenames = {}

for file in files:
    filename = file.split("/")[-1].split(" - ")
    filenames[int(filename[0])] = (filename[1], file.split("/")[-1])

old_numbers = sorted(list(filenames.keys()))

for i, filename in enumerate(old_numbers):
    old_filename = filenames[old_numbers[i]][1]
    new_filename = f"{i+1} - {old_filename.split(' - ')[1]}"
    print(old_filename, " becomes ", new_filename)
    shutil.move("source/" + old_filename, "source/" + new_filename)