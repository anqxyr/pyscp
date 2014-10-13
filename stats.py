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
    _2000 = peewee.BooleanField(null=True)
    acoustic = peewee.BooleanField(null=True)
    adaptive = peewee.BooleanField(null=True)
    admin = peewee.BooleanField(null=True)
    airborne = peewee.BooleanField(null=True)
    alexylva = peewee.BooleanField(null=True)
    alive = peewee.BooleanField(null=True)
    amorphous = peewee.BooleanField(null=True)
    animal = peewee.BooleanField(null=True)
    appliance = peewee.BooleanField(null=True)
    aquatic = peewee.BooleanField(null=True)
    arachnid = peewee.BooleanField(null=True)
    arboreal = peewee.BooleanField(null=True)
    archived = peewee.BooleanField(null=True)
    are_we_cool_yet = peewee.BooleanField(null=True)
    artifact = peewee.BooleanField(null=True)
    artistic = peewee.BooleanField(null=True)
    audio = peewee.BooleanField(null=True)
    auditory = peewee.BooleanField(null=True)
    author = peewee.BooleanField(null=True)
    automaton = peewee.BooleanField(null=True)
    autonomous = peewee.BooleanField(null=True)
    avian = peewee.BooleanField(null=True)
    biohazard = peewee.BooleanField(null=True)
    biological = peewee.BooleanField(null=True)
    black_queen = peewee.BooleanField(null=True)
    blackwood = peewee.BooleanField(null=True)
    broken_god = peewee.BooleanField(null=True)
    building = peewee.BooleanField(null=True)
    cadaver = peewee.BooleanField(null=True)
    canine = peewee.BooleanField(null=True)
    carnivorous = peewee.BooleanField(null=True)
    chaos_insurgency = peewee.BooleanField(null=True)
    chemical = peewee.BooleanField(null=True)
    city = peewee.BooleanField(null=True)
    classical_revival = peewee.BooleanField(null=True)
    clockwork = peewee.BooleanField(null=True)
    clothing = peewee.BooleanField(null=True)
    cognitohazard = peewee.BooleanField(null=True)
    collaboration = peewee.BooleanField(null=True)
    collector_tale = peewee.BooleanField(null=True)
    competitive_eschatology = peewee.BooleanField(null=True)
    compulsion = peewee.BooleanField(null=True)
    computer = peewee.BooleanField(null=True)
    contagion = peewee.BooleanField(null=True)
    container = peewee.BooleanField(null=True)
    corrosive = peewee.BooleanField(null=True)
    creepypasta = peewee.BooleanField(null=True)
    decommissioned = peewee.BooleanField(null=True)
    document = peewee.BooleanField(null=True)
    dr_wondertainment = peewee.BooleanField(null=True)
    ectoentropic = peewee.BooleanField(null=True)
    electrical = peewee.BooleanField(null=True)
    electromagnetic = peewee.BooleanField(null=True)
    electronic = peewee.BooleanField(null=True)
    empathic = peewee.BooleanField(null=True)
    engraved = peewee.BooleanField(null=True)
    essay = peewee.BooleanField(null=True)
    etdp = peewee.BooleanField(null=True)
    euclid = peewee.BooleanField(null=True)
    experiment = peewee.BooleanField(null=True)
    exploration = peewee.BooleanField(null=True)
    extradimensional = peewee.BooleanField(null=True)
    extraterrestrial = peewee.BooleanField(null=True)
    factory = peewee.BooleanField(null=True)
    featured = peewee.BooleanField(null=True)
    feline = peewee.BooleanField(null=True)
    fifthist = peewee.BooleanField(null=True)
    fire = peewee.BooleanField(null=True)
    food = peewee.BooleanField(null=True)
    fungus = peewee.BooleanField(null=True)
    furniture = peewee.BooleanField(null=True)
    game = peewee.BooleanField(null=True)
    game_day = peewee.BooleanField(null=True)
    gaseous = peewee.BooleanField(null=True)
    geological = peewee.BooleanField(null=True)
    glass = peewee.BooleanField(null=True)
    global_occult_coalition = peewee.BooleanField(null=True)
    goi2014 = peewee.BooleanField(null=True)
    goi_format = peewee.BooleanField(null=True)
    gravity = peewee.BooleanField(null=True)
    guide = peewee.BooleanField(null=True)
    hallucination = peewee.BooleanField(null=True)
    heritage = peewee.BooleanField(null=True)
    herman_fuller = peewee.BooleanField(null=True)
    historical = peewee.BooleanField(null=True)
    hive_mind = peewee.BooleanField(null=True)
    horizon_initiative = peewee.BooleanField(null=True)
    hostile = peewee.BooleanField(null=True)
    hub = peewee.BooleanField(null=True)
    humanoid = peewee.BooleanField(null=True)
    incident = peewee.BooleanField(null=True)
    indestructible = peewee.BooleanField(null=True)
    infohazard = peewee.BooleanField(null=True)
    inscribed = peewee.BooleanField(null=True)
    insect = peewee.BooleanField(null=True)
    instrument = peewee.BooleanField(null=True)
    intangible = peewee.BooleanField(null=True)
    interview = peewee.BooleanField(null=True)
    invertebrate = peewee.BooleanField(null=True)
    jewelry = peewee.BooleanField(null=True)
    joke = peewee.BooleanField(null=True)
    keter = peewee.BooleanField(null=True)
    knowledge = peewee.BooleanField(null=True)
    language = peewee.BooleanField(null=True)
    light = peewee.BooleanField(null=True)
    liquid = peewee.BooleanField(null=True)
    location = peewee.BooleanField(null=True)
    loop = peewee.BooleanField(null=True)
    manna_charitable_foundation = peewee.BooleanField(null=True)
    marshall_carter_and_dark = peewee.BooleanField(null=True)
    mathematical = peewee.BooleanField(null=True)
    mechanical = peewee.BooleanField(null=True)
    media = peewee.BooleanField(null=True)
    medical = peewee.BooleanField(null=True)
    memetic = peewee.BooleanField(null=True)
    memory_affecting = peewee.BooleanField(null=True)
    meta = peewee.BooleanField(null=True)
    metallic = peewee.BooleanField(null=True)
    metamorphic = peewee.BooleanField(null=True)
    meteorological = peewee.BooleanField(null=True)
    military = peewee.BooleanField(null=True)
    mimetic = peewee.BooleanField(null=True)
    mind_affecting = peewee.BooleanField(null=True)
    mister = peewee.BooleanField(null=True)
    mobile = peewee.BooleanField(null=True)
    musical = peewee.BooleanField(null=True)
    narrative = peewee.BooleanField(null=True)
    neurological = peewee.BooleanField(null=True)
    neutralized = peewee.BooleanField(null=True)
    nobody = peewee.BooleanField(null=True)
    nyc2013 = peewee.BooleanField(null=True)
    observational = peewee.BooleanField(null=True)
    organic = peewee.BooleanField(null=True)
    orientation = peewee.BooleanField(null=True)
    parasitic = peewee.BooleanField(null=True)
    performance = peewee.BooleanField(null=True)
    physics = peewee.BooleanField(null=True)
    piscine = peewee.BooleanField(null=True)
    plant = peewee.BooleanField(null=True)
    poetry = peewee.BooleanField(null=True)
    portal = peewee.BooleanField(null=True)
    predatory = peewee.BooleanField(null=True)
    predictive = peewee.BooleanField(null=True)
    probability = peewee.BooleanField(null=True)
    project_crossover = peewee.BooleanField(null=True)
    prometheus = peewee.BooleanField(null=True)
    radioactive = peewee.BooleanField(null=True)
    reanimation = peewee.BooleanField(null=True)
    reclamation = peewee.BooleanField(null=True)
    recording = peewee.BooleanField(null=True)
    religious = peewee.BooleanField(null=True)
    reproductive = peewee.BooleanField(null=True)
    reptilian = peewee.BooleanField(null=True)
    ritual = peewee.BooleanField(null=True)
    safe = peewee.BooleanField(null=True)
    sandbox = peewee.BooleanField(null=True)
    sapient = peewee.BooleanField(null=True)
    scp = peewee.BooleanField(null=True)
    sc_plastics = peewee.BooleanField(null=True)
    sculpture = peewee.BooleanField(null=True)
    self_repairing = peewee.BooleanField(null=True)
    self_replicating = peewee.BooleanField(null=True)
    sensory = peewee.BooleanField(null=True)
    sentient = peewee.BooleanField(null=True)
    serpents_hand = peewee.BooleanField(null=True)
    shadow = peewee.BooleanField(null=True)
    skeletal = peewee.BooleanField(null=True)
    sleep = peewee.BooleanField(null=True)
    spacetime = peewee.BooleanField(null=True)
    species = peewee.BooleanField(null=True)
    sphere = peewee.BooleanField(null=True)
    statue = peewee.BooleanField(null=True)
    stone = peewee.BooleanField(null=True)
    structure = peewee.BooleanField(null=True)
    subterranean = peewee.BooleanField(null=True)
    sun = peewee.BooleanField(null=True)
    supplement = peewee.BooleanField(null=True)
    swarm = peewee.BooleanField(null=True)
    tactile = peewee.BooleanField(null=True)
    tale = peewee.BooleanField(null=True)
    telekinetic = peewee.BooleanField(null=True)
    telepathic = peewee.BooleanField(null=True)
    teleportation = peewee.BooleanField(null=True)
    temporal = peewee.BooleanField(null=True)
    thermal = peewee.BooleanField(null=True)
    tool = peewee.BooleanField(null=True)
    toxic = peewee.BooleanField(null=True)
    toy = peewee.BooleanField(null=True)
    transfiguration = peewee.BooleanField(null=True)
    transmission = peewee.BooleanField(null=True)
    unclassed = peewee.BooleanField(null=True)
    uncontained = peewee.BooleanField(null=True)
    unusual_incidents_unit = peewee.BooleanField(null=True)
    vehicle = peewee.BooleanField(null=True)
    virus = peewee.BooleanField(null=True)
    visual = peewee.BooleanField(null=True)
    weapon = peewee.BooleanField(null=True)
    wooden = peewee.BooleanField(null=True)
    xk = peewee.BooleanField(null=True)


db.connect()
db.create_tables([PageStats, VoteStats, WordStats, Tags], safe=True)

###############################################################################


def fill_db():
    PageStats.delete().execute()
    VoteStats.delete().execute()
    WordStats.delete().execute()
    Tags.delete().execute()
    for page in scp_crawler.get_all():
        print("Processing {}".format(page.title))
        gather_page_stats(page)
        gather_vote_stats(page)
        gather_word_stats(page)
        gather_tags(page)


def gather_page_stats(page):
    try:
        rewr = page.authors[1]
    except IndexError:
        rewr = None
    text = BeautifulSoup(page.data).text
    charcount = len(text)
    wordcount = len(text.split(' '))
    PageStats.create(url=page.url,
                     author=page.authors[0].username,
                     rewrite_author=rewr,
                     created=page.history[0].time,
                     rating=page.rating,
                     comments=page.comments,
                     charcount=charcount,
                     wordcount=wordcount,
                     images=len(page.images),
                     revisions=len(page.history))


def gather_vote_stats(page):
    to_insert = []
    for i in page.votes:
        if i.vote == '+':
            vote = 1
        elif i.vote == '-':
            vote = -1
        data_dict = {'url': page.url, 'user': i.user, 'vote': vote}
        to_insert.append(data_dict)
    with db.transaction():
        for idx in range(0, len(to_insert), 500):
            VoteStats.insert_many(to_insert[idx:idx + 500]).execute()


def gather_word_stats(page):
    text = BeautifulSoup(page.data).text
    text = text.replace('[DATA EXPUNGED]', 'DATA_EXPUNGED')
    text = text.replace('[DATA REDACTED]', 'DATA_REDACTED')
    text = text.replace('’', "'")
    text = re.sub(r'Site ([\d]+)', r'Site-\1', text)
    words = re.findall(r"[\w'█_-]+", text)
    words = [i.lower().strip("'") for i in words]
    cn = Counter(words)
    to_insert = []
    for k, v in cn.items():
        data_dict = {'url': page.url, 'word': k, 'count': v}
        to_insert.append(data_dict)
    with db.transaction():
        for idx in range(0, len(to_insert), 500):
            WordStats.insert_many(to_insert[idx:idx + 500]).execute()


def gather_tags(page):
    tags = page.tags
    new_tags = []
    for tag in tags:
        tag = tag.replace('-', '_')
        tag = tag.replace('&', '')
        tag = tag.replace('2000', '_2000')
        new_tags.append(tag)
    Tags.create(url=page.url, **{i: True for i in new_tags})

def main():
    fill_db()


main()
