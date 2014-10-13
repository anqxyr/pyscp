#!/usr/bin/env python3

###############################################################################
# Module Imports
###############################################################################

import arrow
import peewee
import re
import scp_crawler

from bs4 import BeautifulSoup
from collections import Counter

###############################################################################
# Global Constants
###############################################################################

STATDB = '/home/anqxyr/heap/scp_stats.db'

###############################################################################
# Database ORM Classes
###############################################################################

db = peewee.SqliteDatabase(STATDB)


class BaseModel(peewee.Model):

    class Meta:
        database = db


class PageStats(BaseModel):
    url = peewee.CharField(unique=True)
    author = peewee.CharField()
    rewrite_author = peewee.CharField(null=True)
    created = peewee.DateTimeField()
    rating = peewee.IntegerField()
    comments = peewee.IntegerField()
    charcount = peewee.IntegerField()
    wordcount = peewee.IntegerField()
    images = peewee.IntegerField()
    revisions = peewee.IntegerField()


class VoteStats(BaseModel):
    url = peewee.CharField()
    user = peewee.CharField()
    vote = peewee.IntegerField()


class WordStats(BaseModel):
    url = peewee.CharField()
    word = peewee.CharField()
    count = peewee.IntegerField()


class Tags(BaseModel):
    url = peewee.CharField(unique=True)
    _2000 = peewee.BooleanField()
    acoustic = peewee.BooleanField()
    adaptive = peewee.BooleanField()
    admin = peewee.BooleanField()
    airborne = peewee.BooleanField()
    alexylva = peewee.BooleanField()
    alive = peewee.BooleanField()
    amorphous = peewee.BooleanField()
    animal = peewee.BooleanField()
    appliance = peewee.BooleanField()
    aquatic = peewee.BooleanField()
    arachnid = peewee.BooleanField()
    arboreal = peewee.BooleanField()
    archived = peewee.BooleanField()
    are_we_cool_yet = peewee.BooleanField()
    artifact = peewee.BooleanField()
    artistic = peewee.BooleanField()
    audio = peewee.BooleanField()
    auditory = peewee.BooleanField()
    author = peewee.BooleanField()
    automaton = peewee.BooleanField()
    autonomous = peewee.BooleanField()
    avian = peewee.BooleanField()
    biohazard = peewee.BooleanField()
    biological = peewee.BooleanField()
    black_queen = peewee.BooleanField()
    blackwood = peewee.BooleanField()
    broken_god = peewee.BooleanField()
    building = peewee.BooleanField()
    cadaver = peewee.BooleanField()
    canine = peewee.BooleanField()
    carnivorous = peewee.BooleanField()
    chaos_insurgency = peewee.BooleanField()
    chemical = peewee.BooleanField()
    city = peewee.BooleanField()
    classical_revival = peewee.BooleanField()
    clockwork = peewee.BooleanField()
    clothing = peewee.BooleanField()
    cognitohazard = peewee.BooleanField()
    collaboration = peewee.BooleanField()
    collector_tale = peewee.BooleanField()
    competitive_eschatology = peewee.BooleanField()
    compulsion = peewee.BooleanField()
    computer = peewee.BooleanField()
    contagion = peewee.BooleanField()
    container = peewee.BooleanField()
    corrosive = peewee.BooleanField()
    creepypasta = peewee.BooleanField()
    decommissioned = peewee.BooleanField()
    document = peewee.BooleanField()
    dr_wondertainment = peewee.BooleanField()
    ectoentropic = peewee.BooleanField()
    electrical = peewee.BooleanField()
    electromagnetic = peewee.BooleanField()
    electronic = peewee.BooleanField()
    empathic = peewee.BooleanField()
    engraved = peewee.BooleanField()
    essay = peewee.BooleanField()
    etdp = peewee.BooleanField()
    euclid = peewee.BooleanField()
    experiment = peewee.BooleanField()
    exploration = peewee.BooleanField()
    extradimensional = peewee.BooleanField()
    extraterrestrial = peewee.BooleanField()
    factory = peewee.BooleanField()
    featured = peewee.BooleanField()
    feline = peewee.BooleanField()
    fifthist = peewee.BooleanField()
    fire = peewee.BooleanField()
    food = peewee.BooleanField()
    fungus = peewee.BooleanField()
    furniture = peewee.BooleanField()
    game = peewee.BooleanField()
    game_day = peewee.BooleanField()
    gaseous = peewee.BooleanField()
    geological = peewee.BooleanField()
    glass = peewee.BooleanField()
    global_occult_coalition = peewee.BooleanField()
    goi2014 = peewee.BooleanField()
    goi_format = peewee.BooleanField()
    gravity = peewee.BooleanField()
    guide = peewee.BooleanField()
    hallucination = peewee.BooleanField()
    heritage = peewee.BooleanField()
    herman_fuller = peewee.BooleanField()
    historical = peewee.BooleanField()
    hive_mind = peewee.BooleanField()
    horizon_initiative = peewee.BooleanField()
    hostile = peewee.BooleanField()
    hub = peewee.BooleanField()
    humanoid = peewee.BooleanField()
    incident = peewee.BooleanField()
    indestructible = peewee.BooleanField()
    infohazard = peewee.BooleanField()
    inscribed = peewee.BooleanField()
    insect = peewee.BooleanField()
    instrument = peewee.BooleanField()
    intangible = peewee.BooleanField()
    interview = peewee.BooleanField()
    invertebrate = peewee.BooleanField()
    jewelry = peewee.BooleanField()
    joke = peewee.BooleanField()
    keter = peewee.BooleanField()
    knowledge = peewee.BooleanField()
    language = peewee.BooleanField()
    light = peewee.BooleanField()
    liquid = peewee.BooleanField()
    location = peewee.BooleanField()
    loop = peewee.BooleanField()
    manna_charitable_foundation = peewee.BooleanField()
    marshall_carter_and_dark = peewee.BooleanField()
    mathematical = peewee.BooleanField()
    mechanical = peewee.BooleanField()
    media = peewee.BooleanField()
    medical = peewee.BooleanField()
    memetic = peewee.BooleanField()
    memory_affecting = peewee.BooleanField()
    meta = peewee.BooleanField()
    metallic = peewee.BooleanField()
    metamorphic = peewee.BooleanField()
    meteorological = peewee.BooleanField()
    military = peewee.BooleanField()
    mimetic = peewee.BooleanField()
    mind_affecting = peewee.BooleanField()
    mister = peewee.BooleanField()
    mobile = peewee.BooleanField()
    musical = peewee.BooleanField()
    narrative = peewee.BooleanField()
    neurological = peewee.BooleanField()
    neutralized = peewee.BooleanField()
    nobody = peewee.BooleanField()
    nyc2013 = peewee.BooleanField()
    observational = peewee.BooleanField()
    organic = peewee.BooleanField()
    orientation = peewee.BooleanField()
    parasitic = peewee.BooleanField()
    performance = peewee.BooleanField()
    physics = peewee.BooleanField()
    piscine = peewee.BooleanField()
    plant = peewee.BooleanField()
    poetry = peewee.BooleanField()
    portal = peewee.BooleanField()
    predatory = peewee.BooleanField()
    predictive = peewee.BooleanField()
    probability = peewee.BooleanField()
    project_crossover = peewee.BooleanField()
    prometheus = peewee.BooleanField()
    radioactive = peewee.BooleanField()
    reanimation = peewee.BooleanField()
    reclamation = peewee.BooleanField()
    recording = peewee.BooleanField()
    religious = peewee.BooleanField()
    reproductive = peewee.BooleanField()
    reptilian = peewee.BooleanField()
    ritual = peewee.BooleanField()
    safe = peewee.BooleanField()
    sandbox = peewee.BooleanField()
    sapient = peewee.BooleanField()
    scp = peewee.BooleanField()
    sc_plastics = peewee.BooleanField()
    sculpture = peewee.BooleanField()
    self_repairing = peewee.BooleanField()
    self_replicating = peewee.BooleanField()
    sensory = peewee.BooleanField()
    sentient = peewee.BooleanField()
    serpents_hand = peewee.BooleanField()
    shadow = peewee.BooleanField()
    skeletal = peewee.BooleanField()
    sleep = peewee.BooleanField()
    spacetime = peewee.BooleanField()
    species = peewee.BooleanField()
    sphere = peewee.BooleanField()
    statue = peewee.BooleanField()
    stone = peewee.BooleanField()
    structure = peewee.BooleanField()
    subterranean = peewee.BooleanField()
    sun = peewee.BooleanField()
    supplement = peewee.BooleanField()
    swarm = peewee.BooleanField()
    tactile = peewee.BooleanField()
    tale = peewee.BooleanField()
    telekinetic = peewee.BooleanField()
    telepathic = peewee.BooleanField()
    teleportation = peewee.BooleanField()
    temporal = peewee.BooleanField()
    thermal = peewee.BooleanField()
    tool = peewee.BooleanField()
    toxic = peewee.BooleanField()
    toy = peewee.BooleanField()
    transfiguration = peewee.BooleanField()
    transmission = peewee.BooleanField()
    unclassed = peewee.BooleanField()
    uncontained = peewee.BooleanField()
    unusual_incidents_unit = peewee.BooleanField()
    vehicle = peewee.BooleanField()
    virus = peewee.BooleanField()
    visual = peewee.BooleanField()
    weapon = peewee.BooleanField()
    wooden = peewee.BooleanField()
    xk = peewee.BooleanField()


db.connect()
db.create_tables([PageStats, VoteStats, WordStats, Tags], safe=True)

###############################################################################


def fill_db():
    PageStats.delete().execute()
    VoteStats.delete().execute()
    WordStats.delete().execute()
    Tags.delete().execute()
    for page in [scp_crawler.Page('http://www.scp-wiki.net/scp-478')]:
        print("Processing {}".format(page.title))
        gather_page_stats(page)
        gather_vote_stats(page)
        gather_word_stats(page)
        exit()


def gather_page_stats(page):
    try:
        rewr = page.authors[1]
    except IndexError:
        rewr = None
    text = BeautifulSoup(page.data).text
    charcount = len(text)
    wordcount = len(text.split(' '))
    PageStats.create(url=page.url,
                     author=page.authors[0],
                     rewrite_author=rewr,
                     created=page.history[0].time,
                     rating=page.rating,
                     comments=page.comments,
                     charcount=charcount,
                     wordcount=wordcount,
                     images=len(page.images),
                     revisions=len(page.history))


def gather_vote_stats(page):
    for i in page.votes:
        if i.vote == '+':
            vote = 1
        elif i.vote == '-':
            vote = -1
        VoteStats.create(url=page.url, user=i.user, vote=vote)


def gather_word_stats(page):
    text = BeautifulSoup(page.data).text
    text = text.replace('[DATA EXPUNGED]', 'DATA_EXPUNGED')
    text = text.replace('[DATA REDACTED]', 'DATA_REDACTED')
    text = text.replace('’', "'")
    text = re.sub(r'Site ([\d]+)', r'Site-\1', text)
    words = re.findall(r"[\w'█_-]+", text)
    words = [i.lower() for i in words]
    cn = Counter(words)
    import pprint
    pprint.pprint(cn)    

def main():
    fill_db()


main()
