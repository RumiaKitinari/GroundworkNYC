# Source - https://stackoverflow.com/a/68322928
# Posted by Tordanik
# Retrieved 2026-09-21, License - CC BY-SA 4.0

import osmium

class NamesHandler(osmium.SimpleHandler):
    def node(self, n):
        # print(n)
        if 'name' in n.tags:
            print(f'  ({n.tags})')

def main(osmfile):
    NamesHandler().apply_file(osmfile)
    return 0

if __name__ == '__main__':
    main("new-york-260920.osm.pbf")
