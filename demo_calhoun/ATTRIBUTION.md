# Sources and licences

This demo uses only open data. Files marked *derived* were made from the source.

## Seismic refraction (CC BY 4.0)
- **Picks, line positions**: Flinchum, B. A.: Supporting Data Repository: Landscape Curvature
  and Deep Critical Zone Structure. HydroShare,
  http://www.hydroshare.org/resource/340773feb3b341d884f6742b55966609. Calhoun Critical Zone Observatory, South
  Carolina, USA. Licence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
- **Vp models** (`data/refraction/`, *derived*): re-inverted from the authors' expert first-
  arrival picks of lines 6, 10, 11 and 12 with pyGIMLi 1.2.6 as Refrapy's Refrainv runs it
  (scripts/invert_calhoun.py: every 2nd geophone, 60 m deep, lambda 100, z weight 0.1),
  saved in Refrainv's file layout. They are not the authors' published models.
- **Geophones** (`data/stations/`, *derived*): the geophone positions of the pick files,
  placed along the authors' UTM points of each line (allBR.txt), whose surface matches the
  line's elevation file.

## USGS 3DEP (public domain)
- `context/dem_3dep.tif` (*derived*: cut to the lines + 150 m): U.S. Geological Survey, 3D
  Elevation Program 1 m DEM, from the 3DEP elevation image service.

## OpenStreetMap (ODbL)
- The background map: © OpenStreetMap contributors, ODbL,
  https://www.openstreetmap.org/copyright
