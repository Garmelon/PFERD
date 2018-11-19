# Config

- python script as config
- imports PFERD as library
- operates relative to its own path

## Example folder structure

```
.../
  Vorlesungen/
    PFERD/           as symlink, locally or in python's import path
    PFERDconf.py     does things relative to its own location (hopefully)
    GBI/             folder to synchronize files into
      ...
    Prog/            folder to synchronize files into
      ...
```

## Example config

```python
import PFERD

def gbi_filter(ilias_path):
   ...               # rename and move files, or filter them
   return local_path # or None if file should be ignored

kit = PFERD.KIT()
kit.synchronize("crs_855240", "GBI", filter=gbi_filter)
kit.synchronize("crs_851237", "Prog") # default filter preserves paths
```

# Structure

## Things that need to be done

- figure out where config file is located
- get and store shibboleth session cookie
- get and store ilias session cookie
- download specific ilias urls (mostly goto.php, probably)
- parse web page
- determine if logging in is necessary
- authenticate if necessary
- don't re-login if shibboleth session cookie is still valid
- find folders in current folder
- find files to download in current folder
- ignore LA1 test thingy
- crawl folders and create directory-like structure/file paths
- use filter function for paths
- download files to local file paths
- create folders as necessary
- remember downloaded files
- find files that were not previously downloaded
- remove un-downloaded files
- remove unnecessary folders (prompt user before deleting!)
- logging
	- display crawl progress
	- display structure of found files using neat box drawing characters
	- display download progress

## How those things are usually done

Step 3. to 5. are run for each synchronize() call.

1. launch script
	- load cookie files
2. authenticate
   (assuming enough time has passed for the session cookies to become invalid)
	- prompt user for username
	- prompt user for password (no echo)
	- somehow obtain valid session cookies
3. crawl
	- start at the id specified in synchronize() args
	- search for folders and files to download
	- build directory structure
4. download
	- run each path through filter function
	- if file was not filtered:
		- download file and save result to filtered path
		- use sync directory specified in synchronize() args
	- remember the filtered path for later
5. cleanup
	- search sync directory for files
	- for each file not previously downloaded:
		- prompt user if they want to delete the file (default: No)
		- delete file if user answered Yes
