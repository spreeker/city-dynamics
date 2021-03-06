"""
Access the druktemonitor project data on the data store.

For now the convention is that only relevant files are in the datastore and
the layout there matches the layout expected by our data loading scripts.

(We may have to complicate this in the future if we get to automatic
delivery of new data for this project.)
"""
import os
import argparse
import logging
import configparser

from swiftclient.client import Connection

logging.getLogger('requests').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('swiftclient').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

FORMAT = '%(asctime)-15s %(message)s'
logging.basicConfig(format=FORMAT, level=logging.DEBUG)

config_auth = configparser.RawConfigParser()
config_auth.read('auth.conf') 

config_src = configparser.RawConfigParser()
config_src.read('sources.conf') 

# find object store password in environmental variables
OBJECTSTORE_PASSWORD = os.environ['EXTERN_DATASERVICES_PASSWORD']

OS_CONNECT = {
    'auth_version': config_auth.get('extern_dataservices','ST_AUTH_VERSION'),
    'authurl': config_auth.get('extern_dataservices','OS_AUTH_URL'),
    'tenant_name': config_auth.get('extern_dataservices','OS_TENANT_NAME'),
    'user': config_auth.get('extern_dataservices','OS_USERNAME'),
    'os_options': {
        'tenant_id': config_auth.get('extern_dataservices','OS_PROJECT_ID'),  # Project ID
        'region_name': config_auth.get('extern_dataservices','OS_REGION_NAME')
    },
    'key': OBJECTSTORE_PASSWORD
}


datasets = [config_src.get(x, 'FOLDER_FTP') for x in config_src.sections()]


def get_full_container_list(conn, container, **kwargs):
    
    # Note: taken from the bag_services project
    limit = 10000
    kwargs['limit'] = limit
    page = []
    seed = []
    
    _, page = conn.get_container(container, **kwargs)
    seed.extend(page)
    
    while len(page) == limit:
        # keep getting pages..
        kwargs['marker'] = seed[-1]['name']
        _, page = conn.get_container(container, **kwargs)
        seed.extend(page)
        
    return seed


def download_container(conn, container, datadir):
    # list of container's content
    content = get_full_container_list(conn, container['name'])
    
    # loop over files
    for obj in content:
        # check if object type is not application or dir, or a "part" file
        if obj['content_type'] != 'application/directory' and 'part' not in obj['name']:
            # target filename of object
            target_filename = os.path.join(datadir, obj['name'])
            # write object in target file
            with open(target_filename, 'wb') as new_file:
                _, obj_content = conn.get_object(container['name'], obj['name'])
                new_file.write(obj_content)


def download_containers(conn, datasets, datadir):
    """
    Download the citydynamics datasets from object store.
    
    Simplifying assumptions:
    * layout on data store matches intended layout of local data directory
    * datasets do not contain nested directories
    * assumes we are running in a clean container (i.e. empty local data dir)
    * do not overwrite / delete old data
    """
    logger.debug('Checking local data directory exists and is empty')
    if not os.path.exists(datadir):
        raise Exception('Local data directory does not exist.')
        
    listing = os.listdir(datadir)
    if listing:
        if len(listing) == 1 and listing[0] == 'README':
            # Case where the 'data' dictory is used from a fresh checkout.
            pass
        else:
            raise Exception('Local data directory not empty!')
            
    #logger.debug('Establishing object store connection.')
    resp_headers, containers = conn.get_account()
    
    logger.debug('Downloading containers ...')
    
    for c in containers:
        if c['name'] in datasets:
            print(c['name'])
            download_container(conn, c, datadir)


def main(datadir):
    conn = Connection(**OS_CONNECT)
    download_containers(conn, datasets, datadir)


if __name__ == '__main__':
    desc = "Download data from object store."
    parser = argparse.ArgumentParser(desc)
    parser.add_argument('datadir', type=str, help='Local data directory.', nargs=1)
    args = parser.parse_args()

    # Check whether local cached downloads should be used.
    ENV_VAR = 'EXTERNAL_DATASERVICES_USE_LOCAL'
    use_local = True if os.environ.get(ENV_VAR, '') == 'TRUE' else False

    if not use_local:
        main(args.datadir[0])
    else:
        logger.info('No download from datastore requested, quitting.')