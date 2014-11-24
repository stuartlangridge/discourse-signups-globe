"""Turn discourse data into a cool rotating globe showing when everyone signed up.

    You will need dump.sql from your discourse backup (/var/discourse/shared/standalone/backups/default/)
    which you then gzip to make it smaller. You'll also need a bunch of matplotlib stuff, and you'll need
    GeoLiteCity.dat from http://geolite.maxmind.com/download/geoip/database/GeoLiteCity.dat.gz, ungzipped.

    Stuff that's tweakable:
    1. How a person appears on the map is defined by the EFFECTS list; this is a list of params to pass
       to Basemap.scatter, one per frame (so a person appears on day N and their marker is drawn as
       defined by EFFECTS[0], then on day N+1 their marker is defined by EFFECTS[1], etc). The final
       entry in EFFECTS "sticks", so their marker stays on there.
    2. How the globe spins. In handle_one_frame, lat_0 and lon_0 define where on the globe the camera
       is pointed at. Compute it as a function of "counter", which is the frame number.
    3. Colours and text styles are all set on every frame in handle_one_frame, so tweak them as you please.
    4. How big the resulting images are is set by the dpi parameter to plt.savefig. Note that if you want
       to use avconv to create an mp4 out of it, then both height and width of the images must be divisible
       by 2.

    Inspired by https://github.com/pierrrrrrre/PyGeoIpMap, at least because I had no idea that Basemap existed.

    Also includes download data for our show; get lines from your apache log and put them in bvdl.log.gz.

    @sil, November 2014.
    http://badvoltage.org
"""
import gzip, datetime, GeoIP, math, os
import matplotlib
# Anti-Grain Geometry (AGG) backend so PyGeoIpMap can be used 'headless'
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.basemap import Basemap

f = gzip.open('dump.sql.gz', 'rb')
file_content = f.read()
f.close()
users = []
in_users = False
required_fields = ["id", "username", "registration_ip_address", 
    "ip_address", "created_at"]
for line in file_content.split("\n"):
    if in_users:
        values = line.split("\t")
        data = dict(zip(fields, values))
        nd = {}
        ok = True
        for required in required_fields:
            val = data.get(required)
            if val:
                nd[required] = val
            else:
                ok = False
        if ok: users.append(nd)
    if not line.strip():
        in_users = False
    if line.startswith("COPY users "):
        in_users = True
        fields = [x.strip() for x in
            line.replace("COPY users (", "").replace(") FROM stdin;", "").split(",")]

# convert everyone to have one IP address only and nice data formats
gi = GeoIP.open("GeoLiteCity.dat", GeoIP.GEOIP_STANDARD)
nu = []
for user in users:
    user["created_at"] = datetime.datetime.strptime(user["created_at"], "%Y-%m-%d %H:%M:%S.%f").date()
    ip = None
    if user["registration_ip_address"] and user["registration_ip_address"] != "\\N":
        ip = user["registration_ip_address"]
    if not ip:
        ip = user["ip_address"]
    if ip and ip != "\\N":
        del(user["registration_ip_address"])
        del(user["ip_address"])
        user["ip"] = ip
        loc = gi.record_by_addr(ip)
        user["loc"] = {"lat": loc["latitude"], "lon": loc["longitude"]}
        nu.append(user)
users = nu

EFFECTS = [
    { "color": "#ffffff", "alpha": 0.6, "s": 60 },
    { "color": "#ffffcc", "alpha": 0.8, "s": 40 },
    { "color": "#ffff99", "alpha": 0.8, "s": 10 },
    { "color": "#ffff66", "alpha": 0.7, "s": 5 },
    { "color": "#ffff33", "alpha": 0.6, "s": 2 },
    { "color": "#ffff00", "alpha": 0.5, "s": 1 }
]

END_AT = datetime.datetime.now().date()
END_AT = datetime.datetime(year=2015,month=2,day=19).date()

frames = {}
for user in users:
    # add a dot for my frame and all frames afterwards
    ndate = user["created_at"]
    framecount = 0
    while 1:
        if ndate not in frames:
            frames[ndate] = []
        frames[ndate].append({"count": framecount, "loc": user["loc"]})
        ndate += datetime.timedelta(days=1)
        framecount += 1
        if ndate > END_AT: break

# include downloads
f = gzip.open('bvdl.log.gz', 'rb')
file_content = f.read()
f.close()
dls = {}
for line in file_content.split("\n"):
    parts = line.split()
    if len(parts) < 4:
        print "Line fail", line
        continue
    ip = parts[0]
    dt = parts[3].split("[")[1].split(":")[0]
    ddt = datetime.datetime.strptime(dt, "%d/%b/%Y").date()
    key = repr(ddt) + repr(ip) # stash in dict to remove more than one dl per ip per day
    loc = gi.record_by_addr(ip)
    if not loc:
        print "ip fail", ip
        continue
    dls[key] = {"date": ddt, "loc": {"lat": loc["latitude"], "lon": loc["longitude"]}}

for data in dls.values():
    ndate = data["date"]
    framecount = 0
    while 1:
        if ndate not in frames:
            frames[ndate] = []
        frames[ndate].append({"count": framecount, "loc": data["loc"]})
        ndate += datetime.timedelta(days=1)
        framecount += 1
        if framecount >= len(EFFECTS): break

START_LON = 20
END_LON = -120
LON_DIRECTION = -1 # rotate so a point on the globe goes to the east
COMPLETE_LOOPS = 2 # number of full rotations in addition to moving between start and end

total_lon_traversed = (COMPLETE_LOOPS * 360)
if LON_DIRECTION == -1:
    total_lon_traversed = total_lon_traversed + START_LON + (180 - END_LON)
else:
    total_lon_traversed = total_lon_traversed + (180 - START_LON) + END_LON

def handle_one_frame(inp):
    counter, dt, data = inp
    outfile = dt.strftime("out-%03d.png" % (counter - 1,))
    points = {}
    for point in data:
        if point["count"] >= len(EFFECTS): point["count"] = len(EFFECTS) - 1
        if point["count"] not in points:
            points[point["count"]] = []
        points[point["count"]].append(point)
    frac = float(counter) / len(frames)
    lon_0 = ((START_LON + (frac * total_lon_traversed * LON_DIRECTION)) % 360) - 180
    lat_0 = math.sin(3.141 * float(counter) / 90) * 20 + 10
    #print lat_0; counter +=1; continue
    m = Basemap(projection='ortho',lat_0=lat_0,lon_0=lon_0,resolution='c')
    m.drawmapboundary(fill_color='black')
    m.drawcoastlines(linewidth=1.25, color="#006600")
    m.drawcoastlines(linewidth=0.75, color="#00ff00")
    m.drawcoastlines(linewidth=0.25, color="#aaffaa")
    m.fillcontinents(color='#003300',lake_color='black')
    m.drawcountries(linewidth=0.25, color="black")
    for effect, pointdata in points.items():
        lons = [x["loc"]["lon"] for x in pointdata]
        lats = [x["loc"]["lat"] for x in pointdata]
        x, y = m(lons, lats)
        m.scatter(x,y, marker='o', zorder=10, **EFFECTS[effect])
    plt.title(dt.strftime("%d %B %Y"), loc="left", family="monospace")
    plt.savefig(outfile, dpi=146, bbox_inches='tight',facecolor="black")
    plt.close()
    print "Done frame %s of %s" % (counter, len(frames.keys()))
    #if outfile == "frame-2013-11-30.png": break

# do it with multiprocessing because it's faster
to_process = [(x[0], x[1][0], x[1][1]) for x in 
    enumerate(sorted(frames.items(), lambda a,b: cmp(a[0],b[0])))]
import multiprocessing
pool = multiprocessing.Pool()
result1 = pool.map(handle_one_frame, to_process)
#os.system('avconv -framerate 2 -i "out-%03d.png" -c:v libx264 -pix_fmt yuv420p out.mp4')



