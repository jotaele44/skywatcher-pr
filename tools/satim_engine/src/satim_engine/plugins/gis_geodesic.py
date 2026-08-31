"""WGS84 geodesic primitives for SATIM GIS joins.

This removes degree-distance as the production metric while keeping the legacy
degree column available for reproducibility. Vincenty inverse is used with a
spherical fallback only for rare non-convergent antipodal pairs.
"""
from __future__ import annotations
import math
A=6378137.0; F=1/298.257223563; B=(1-F)*A

def _valid(lon,lat):
 lon,lat=float(lon),float(lat)
 if not math.isfinite(lon) or not math.isfinite(lat) or not -180<=lon<=180 or not -90<=lat<=90: raise ValueError("invalid WGS84 coordinate")
 return lon,lat

def _haversine(lon1,lat1,lon2,lat2):
 p1,p2=map(math.radians,(lat1,lat2)); dp=p2-p1; dl=math.radians(lon2-lon1); h=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2; return 6371008.8*2*math.atan2(math.sqrt(h),math.sqrt(max(0,1-h)))

def distance_m(lon1,lat1,lon2,lat2):
 lon1,lat1=_valid(lon1,lat1); lon2,lat2=_valid(lon2,lat2)
 if (lon1,lat1)==(lon2,lat2): return 0.0
 p1,p2=map(math.radians,(lat1,lat2)); U1=math.atan((1-F)*math.tan(p1)); U2=math.atan((1-F)*math.tan(p2)); L=math.radians(lon2-lon1); lam=L
 for _ in range(200):
  sl,cl=math.sin(lam),math.cos(lam); ss=math.sqrt((math.cos(U2)*sl)**2+(math.cos(U1)*math.sin(U2)-math.sin(U1)*math.cos(U2)*cl)**2)
  if ss==0:return 0.0
  cs=math.sin(U1)*math.sin(U2)+math.cos(U1)*math.cos(U2)*cl; sigma=math.atan2(ss,cs); sa=math.cos(U1)*math.cos(U2)*sl/ss; c2a=1-sa*sa; c2sm=0 if c2a==0 else cs-2*math.sin(U1)*math.sin(U2)/c2a; C=F/16*c2a*(4+F*(4-3*c2a)); nxt=L+(1-C)*F*sa*(sigma+C*ss*(c2sm+C*cs*(-1+2*c2sm*c2sm)))
  if abs(nxt-lam)<1e-12: lam=nxt; break
  lam=nxt
 else:return _haversine(lon1,lat1,lon2,lat2)
 u2=c2a*(A*A-B*B)/(B*B); aa=1+u2/16384*(4096+u2*(-768+u2*(320-175*u2))); bb=u2/1024*(256+u2*(-128+u2*(74-47*u2))); ds=bb*ss*(c2sm+bb/4*(cs*(-1+2*c2sm*c2sm)-bb/6*c2sm*(-3+4*ss*ss)*(-3+4*c2sm*c2sm))); return B*aa*(sigma-ds)

def bbox_distance_m(lat,lon,bbox):
 min_lon,min_lat,max_lon,max_lat=map(float,bbox)
 if min_lon<=lon<=max_lon and min_lat<=lat<=max_lat:return 0.0
 qlon=min(max(float(lon),min_lon),max_lon); qlat=min(max(float(lat),min_lat),max_lat)
 return distance_m(float(lon),float(lat),qlon,qlat)
