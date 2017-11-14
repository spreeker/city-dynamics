import os
import argparse
import configparser
import datetime
import pandas as pd
import re
import csv
import numpy as np

def fix_times(t, d):
    if t >= 24:
        t -= 24
        if d == 1:
            d = 7
        else:
            d -= 1	
    return t, d

def get_datetime(row):
    t = datetime.time(row.tijd_numeric, 0)
    d = [int(e) for e in row.date.split('-')]
    d = datetime.date(d[0], d[1], d[2])
    dt = datetime.datetime.combine(d, t)
    return dt

def parse_gvb(tablename, conn, datadir, rittenpath='Ritten GVB 24jun2017-7okt2017.csv', locationspath='Ortnr - coordinaten (ingangsdatum dec 2015) met LAT LONG.xlsx'):
    # read raw ritten
    rittenpath = os.path.join(datadir, rittenpath)
    ritten = pd.read_csv(rittenpath, skiprows=2, header=None)
    ritten.columns = ['weekdag', 'tijdstip', 'ortnr_start', 'haltenaam_start', 'ortnr_eind', 'tot_ritten']
    ritten.drop('haltenaam_start', axis=1, inplace=True)
    
    # read locations
    locationspath = os.path.join(datadir, locationspath)
    locations = pd.read_excel(locationspath)
    locations.drop(['X_COORDINAAT', 'Y_COORDINAAT'], axis=1, inplace=True)
    
    # drop unknown haltes
    locations = locations.loc[locations.haltenaam != '-- Leeg beeld --']
    
    # add start to ritten
    newnames = dict(OrtNr='ortnr_start', haltenaam='haltenaam_start', LAT='lat_start', LONG='lng_start')
    locations.rename(columns=newnames, inplace=True)
    ritten = pd.merge(ritten, locations, on='ortnr_start')
    
    # add end to ritten
    newnames = dict(ortnr_start='ortnr_eind', haltenaam_start='haltenaam_eind', lat_start='lat_eind', lng_start='lng_eind')
    locations.rename(columns=newnames, inplace=True)
    ritten = pd.merge(ritten, locations, on='ortnr_eind')
    
    # incoming ritten
    incoming = ritten.groupby(['haltenaam_eind', 'weekdag', 'tijdstip'])['tot_ritten'].sum().reset_index()
    incoming.rename(columns={'haltenaam_eind':'halte', 'tot_ritten':'incoming'}, inplace=True)
    
    # outgoing ritten
    outgoing = ritten.groupby(['haltenaam_start', 'weekdag', 'tijdstip'])['tot_ritten'].sum().reset_index()
    outgoing.rename(columns={'haltenaam_start': 'halte', 'tot_ritten':'outgoing'}, inplace=True)
    
    # merge incoming, outgoing
    inout = pd.merge(incoming, outgoing, on=['halte', 'weekdag', 'tijdstip'])
    
    # del incoming, outgoing, data
    del incoming, outgoing, ritten
    
    # fix tijdstip to hour
    inout['tijd'] = [t.split(':')[0] + ':00' for t in inout.tijdstip]
    
    # aggregate to hour
    inout = inout.groupby(['halte', 'weekdag', 'tijd'])['incoming', 'outgoing'].sum().reset_index()
    
    # dag van de week to numeric
    days = dict(ma=1, di=2, wo=3, do=4, vr=5, za=6, zo=7)
    inout['day_numeric'] = [days[d] for d in inout.weekdag]
        
    # time range
    inout['tijd_numeric'] = [int(t.split(':')[0]) for t in inout.tijd]

    # fix hour over 24
    inout.drop('weekdag', axis=1, inplace=True)
    fixed_time_day = [fix_times(t, d) for t, d in zip(inout.tijd_numeric, inout.day_numeric)]
    inout['tijd_numeric'] = [x[0] for x in fixed_time_day]
    inout['day_numeric'] = [x[1] for x in fixed_time_day]

    # add timestamp, fake date, mon 2 oct - sun 8 oct
    dates = ['2017-10-0' + str(i) for i in range(2, 9)]
    inout['date'] = [dates[d-1] for d in inout.day_numeric]
    inout['timestamp'] = [get_datetime(row) for _, row in inout.iterrows()]    
    
    # mean locaties
    locations.rename(columns={'ortnr_eind':'ortnr', 'haltenaam_eind':'halte', 'lat_eind':'lat', 'lng_eind':'lon'}, inplace=True)
    mean_locations = locations.groupby('halte')['lat', 'lon'].mean().reset_index()
    mean_locations = mean_locations[mean_locations.halte != '-- Leeg beeld --']
    
    # add lat/long coordinates
    inout = pd.merge(inout, mean_locations, on='halte')

    # drop obsolete columns
    inout.drop(['tijd_numeric', 'tijd', 'date'], axis=1, inplace=True)
    
    # write to database
    inout.to_sql(name=tablename, con=conn, index=False, if_exists='replace')


def parse_google(conn, tablename, datadir):
    location_files = [x for x in os.listdir(datadir) if x.startswith('locations')]

    locations = pd.DataFrame()
    for file in location_files:
        file_path = os.path.join(datadir, file)
        locations = pd.concat([locations, pd.read_csv(file_path, sep=';')])

    locations.drop('Unnamed: 0',axis=1, inplace=True)
    locations.address = locations.address.str.replace(',',' ')

    measures = pd.read_csv(datadir + r'\ams_google_data.csv',
                      encoding='cp1252')

    _, measures['Location_address'] = measures.search_term.str.split('  ',1).str
    measures.drop('name', axis=1, inplace=True)

    google_pop_times = measures.merge(locations, left_on='Location_address', right_on='address')

    to_drop = ['batch','batch_time',
               'search_term','Location_address',
               'place_id','rating','popular_times']

    google_pop_times.drop(to_drop, axis=1, inplace=True)

    google_pop_times.rename(columns={'lng':'lon'}, inplace=True)

    google_pop_times.scrape_time = pd.to_datetime(google_pop_times.scrape_time)

    google_pop_times.to_sql(name=tablename, con=conn, index=False, if_exists='replace')


def parse_mora(tablename, conn, datadir, filename='MORA_data_data.csv'):
    # read mora csv
    path = os.path.join(datadir, filename)
    df = pd.read_csv(path, delimiter=';')

    # select Hoofdrubriek, Subrubriek, Lattitude, Longitude
    df_select = df.loc[:,['Hoofdrubriek', 'Subrubriek', 'Lattitude', 'Longitude']]

    # rename columns
    df_select.rename(columns={'Hoofdrubriek':'hoofdrubriek', 'Subrubriek':'subrubriek', 'Lattitude':'lat', 'Longitude':'lon'}, inplace=True)

    # add date time column als datetime object
    df_select['timestamp'] = pd.to_datetime(df['AA_ADWH_DATUM_AFGEROND'], format="%d-%m-%Y %H:%M:%S")

    # filter NaN
    indx = np.logical_or(np.isnan(df_select.lat), np.isnan(df_select.lon))
    indx = np.logical_not(indx)
    df_select = df_select.loc[indx, :]

    df_select.to_sql(name=tablename, con=conn, index=False, if_exists='replace')