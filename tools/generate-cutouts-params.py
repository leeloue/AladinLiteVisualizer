#!/usr/bin/env python

import pyvo

from astropy.coordinates import SkyCoord
from astropy.table import Table

import numpy as np

from mocpy import MOC

tap_service = pyvo.dal.TAPService('http://simbad.u-strasbg.fr/simbad/sim-tap')

query = """
    SELECT TOP 100000 ra, dec, main_id, oid, otype, galdim_majaxis
    FROM basic
    WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', 84.67567, -69.11625, 0.53917)) = 1
          AND otype != '*'
    ORDER BY nbref DESC
"""
resultset = tap_service.search(query)
table = resultset.to_table()

sc = SkyCoord(table['ra'], table['dec'], unit='deg')
hips_coverage = MOC.load('hips/F658N/Moc.fits')

mask = hips_coverage.contains_skycoords(sc)

filtered_table = table[mask]

mask_galdim_majaxis_missing = np.ma.getmask(filtered_table['galdim_majaxis'])

params_table = Table()
params_table['ra'] = filtered_table['ra']
params_table['dec'] = filtered_table['dec']
params_table['fov'] = filtered_table['galdim_majaxis'] / 60.
# default value for objects without galdim majaxis values
params_table['fov'][mask_galdim_majaxis_missing] = 0.005
params_table['width'] = 250
params_table['height'] = 250
params_table['hips'] = './hips/F658N'
params_table['format'] = 'png'
params_table['stretch'] = 'sqrt'
params_table['output'] = ['my-cutouts/' + str(row['oid']) + '.png' for row in filtered_table]
params_table['label'] = filtered_table['main_id'] + ' (' + filtered_table['otype'] + ')'


params_table.write('cutout-params.csv', format='csv', overwrite=True)

