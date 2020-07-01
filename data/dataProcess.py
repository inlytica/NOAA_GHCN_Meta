#*********************************************************************************************************************************************
# Import modules
#*********************************************************************************************************************************************
from app import app

import pandas as pd
import dask.dataframe as dd
from dask.distributed import Client


import dash
from dash.dependencies import Input, Output, State
from dash.exceptions import PreventUpdate


import numpy as np

import pyarrow as pa

import uuid
import redis

#*********************************************************************************************************************************************
# Connect to redis server
#*********************************************************************************************************************************************
redis_host = 'localhost'
redis_port = 6379
redis = redis.StrictRedis(host = redis_host, port=redis_port)

# Define functions that serialize and compress data to send to redis and to get data back from redis.

def setRedis(keyname,data,sessionID):
    inData = pa.serialize(data).to_buffer()
    compressLength = len(inData)
    inDataCompress= pa.compress(inData,asbytes=True)
    inDataDict = {'compressLength':compressLength,'inDataCompress':inDataCompress}
    keyDict = {'key':f"{keyname}Cache{sessionID}"}
    redis.hmset(keyDict['key'],inDataDict)

def getRedis(keyname,sessionID):

    keyDict = {'key':f"{keyname}Cache{sessionID}"}

    cacheDataCompress = redis.hget(keyDict['key'],'inDataCompress')
    cacheDataLen = int(redis.hget(keyDict['key'],'compressLength'))
    cacheSerialize = pa.decompress(cacheDataCompress,decompressed_size=cacheDataLen)
    cache = pa.deserialize(cacheSerialize)
    return cache

def filter_by_mapbox_data(dataFrame,relayoutData,selectedData):
    df = dataFrame



    if  relayoutData.get('dragmode') == 'pan':
        df = df 
    elif relayoutData.get('dragmode') is not None and selectedData is not None:  
        stationList = []
        for i in selectedData['points']:
            stationList.append(i['text'])
        df = df.query('station.isin(@stationList)')
    elif relayoutData != {'autosize': True} and relayoutData is not None and relayoutData.get('dragmode') is None:

        array=np.array((relayoutData['mapbox._derived']['coordinates']))
        minLon = array[:,0].min()
        maxLon = array[:,0].max()
        minLat = array[:,1].min()
        maxLat = array[:,1].max()

        df = df.query('@minLat <= latitude <= @maxLat & @minLon <= longitude <= @maxLon') 
    
    return df





#*********************************************************************************************************************************************
#Load inventory file text file, compute as pandas, remove extraneous spaces, split into columns
#*********************************************************************************************************************************************

if __name__ == 'dataProcess':
    client = Client()

inventory = dd.read_csv('s3://noaa-ghcn-pds/ghcnd-inventory.txt',storage_options={'anon':True},
                    header=None,names=['Data']).compute()

inventory['Data'] = inventory['Data'].apply(lambda x: ' '.join(x.split()))

inventory = inventory['Data'].str.split(' ',expand=True)

inventory.columns=['station','latitude','longitude','measure','begin','end']

inventory = inventory.astype({'latitude':'float64','longitude':'float64','begin':'int64', 'end':'int64'})

#*********************************************************************************************************************************************
# Create session ID and store
#*********************************************************************************************************************************************

@app.callback(Output('sessionStore','data'),
            [
                Input('sessionGenDiv','children')
                ]
            )
def sessionStore(sessionGenDiv):
    return str(uuid.uuid4())


#*********************************************************************************************************************************************
# Create dataframe for mapbox image.  Filtered by yearSlider and measures
#*********************************************************************************************************************************************


@app.callback(Output('dataProcessMapBox','children'),
                    [
                        Input('sessionStore','data'),
                        Input('yearSlider','value'),
                        Input('measures','value'),
                        Input('dateRangeInsideOutside','value'),
                        Input('fixFilter','value')],
                       [State('mapbox','relayoutData')

                    ]
                    )
def dataProcess(sessionStoreData,yearSliderValue,measuresValue,dateRangeInsideOutsideValue,fixFilterValue,relayoutData):
    ctx = dash.callback_context

    if relayoutData.get('dragmode') == 'lasso' and ctx.triggered[0]['prop_id'].split('.')[0] == 'yearSlider' and fixFilterValue in ['Mapbox','Measures']:
         raise PreventUpdate

    if dateRangeInsideOutsideValue == 'in':
        df = inventory.query('measure.isin(@measuresValue) &  begin <= @yearSliderValue[0] & end >= @yearSliderValue[1]')
    elif dateRangeInsideOutsideValue == 'out':
        df = inventory.query('measure.isin(@measuresValue) &  begin >= @yearSliderValue[0] & end <= @yearSliderValue[1]')
    else:
        df = inventory.query('measure.isin(@measuresValue) &  begin == @yearSliderValue[0] & end == @yearSliderValue[1]')

    df = df[['station','latitude','longitude']]
    df = df.drop_duplicates(subset='station',keep='first')




    setRedis('mapbox',df,sessionStoreData)

    ctx = dash.callback_context

    return 'Computed'


@app.callback(Output('mapboxCenterStore','data'),
                [
                Input('mapbox','relayoutData')
                ])
def mapboxCenterCoords(relayoutData):
    if relayoutData is not None and relayoutData.get('dragmode') is not None:
        raise PreventUpdate
    elif relayoutData != {'autosize': True} and relayoutData is not None:
        centerLon = relayoutData['mapbox.center']['lon']
        centerLat = relayoutData['mapbox.center']['lat']
        zoom = relayoutData['mapbox.zoom']    
    else: 
        centerLon = -94.676392
        centerLat = 39.106667
        # centerLon = -77.07
        # centerLat = 38.92
        zoom = 3

    return {'centerLon':centerLon,'centerLat':centerLat,'zoom':zoom}

#*********************************************************************************************************************************************
# Create dictionary for measure callback options.  Filtered by yearSlider and mapbox relayout
#*********************************************************************************************************************************************


@app.callback(Output('dataProcessMeasure','children'),
                   [
                        Input('sessionStore','data'),
                        Input('yearSlider','value'),
                        Input('mapbox','relayoutData'),
                        Input('mapbox','selectedData'),
                        Input('fixFilter','value'),
                        Input('dateRangeInsideOutside','value')

                    ]
                    )

def dataProcess(sessionStoreData,yearSliderValue,relayoutData,selectedData,fixFilterValue,dateRangeInsideOutsideValue):

    if fixFilterValue == 'Measures':
        #measureInventory = inventory
        raise PreventUpdate

    else:

    
        if yearSliderValue != [None,None]:

            if dateRangeInsideOutsideValue == 'in':
                measureInventory = inventory.query('begin <= @yearSliderValue[0] & end >= @yearSliderValue[1]')
            elif dateRangeInsideOutsideValue == 'out':
                measureInventory = inventory.query('begin >= @yearSliderValue[0] & end <= @yearSliderValue[1]')
            else:
                measureInventory = inventory.query('begin == @yearSliderValue[0] & end == @yearSliderValue[1]')

        else:
            measureInventory = inventory

        measureInventory = filter_by_mapbox_data(measureInventory,relayoutData,selectedData)

    measures = list(measureInventory.measure.unique())

    options = []
    for measure in measures:
        optionDict = {'label':f'{measure}   ', 'value':measure}
        options.append(optionDict) 

    setRedis('measureOptions',options,sessionStoreData)

    return 'Computed'

#*********************************************************************************************************************************************
# Create List for measure values to be supplied by buttons.  
#*********************************************************************************************************************************************

@app.callback(Output('dataProcessMeasureValue','children'),
            [
            Input('sessionStore','data'),
            Input('measureChooseAll','n_clicks'),
            Input('measureChooseCore','n_clicks'),
            Input('measureChooseSelf','n_clicks')
            ]
            )
def measureValue(sessionStoreData,chooseAll,chooseCore,chooseSelf):

    clicks = chooseAll + chooseCore + chooseSelf

    ctx = dash.callback_context

    optionList = list(inventory.measure.unique())
    
    if ctx.triggered[0]['prop_id'].split('.')[0] == 'sessionStore' and clicks == 0:
        values =  optionList
    elif ctx.triggered[0]['prop_id'].split('.')[0] == 'measureChooseAll':
        values = optionList
    elif ctx.triggered[0]['prop_id'].split('.')[0] == 'measureChooseCore':
        values =  ['PRCP','SNOW','SNWD','TMAX','TMIN']
    elif ctx.triggered[0]['prop_id'].split('.')[0] == 'measureChooseSelf':
        values = [] 
    else:
        raise PreventUpdate

    setRedis('measureValue',values,sessionStoreData)

    return 'Computed'

#*********************************************************************************************************************************************
# Create list of values and min, max for yearSlider.  Filtered by measure values and mapbox relayout
#*********************************************************************************************************************************************

@app.callback(Output('dataProcessYearSlider','children'),
    
            [
            Input('sessionStore','data'),
            Input('mapbox','relayoutData'),
            Input('mapbox','selectedData'),
            Input('measures','value'),
            Input('fixFilter','value')
            ]
            )
def measureValue(sessionStoreData,relayoutData,selectedData,measuresValue,fixFilterValue):
    min = inventory.begin.min()
    max = inventory.end.max()

    ctx = dash.callback_context

    if ctx.triggered[0]['prop_id'].split('.')[0] == 'measures' and len(ctx.triggered)>1:
        value = [min,max]

    elif fixFilterValue == 'Time':
        raise PreventUpdate
    elif relayoutData.get('dragmode') == 'lasso' and selectedData is None:
        raise PreventUpdate

    else:
    
        #df = inventory.query('measure.isin(@measuresValue)')
        df = inventory

        df = filter_by_mapbox_data(df,relayoutData,selectedData)

        value = [df.begin.min(),df.end.max()]

    markColor = '#EBEBEB'
    marks = {}
    for year in range(min,max,20):
        marks.update({year:{'label':str(year),'style':{'color':markColor}}})
    marks.update({max:{'label':str(max),'style':{'color':markColor}}})
  
    sliderDict = {'min':min,'max':max,'value':value,'marks':marks}

    setRedis('sliderValue',sliderDict,sessionStoreData)  

    return 'Computed'


#*********************************************************************************************************************************************
# Create selected range for Year Slider.  
#*********************************************************************************************************************************************

@app.callback(Output('yearRange','children'),
                [Input('yearSlider','value')])
def yearRange(yearSliderValue):
    return f'Selected dates: {yearSliderValue[0]} - {yearSliderValue[1]}'


#*********************************************************************************************************************************************
# Generate data for download
#*********************************************************************************************************************************************

@app.callback(Output('downloadSpinnerOutput','children'),
                       [
                        Input('generateCsvButton','n_clicks'),
                        Input('sessionStore','data')],
                        [State('yearSlider','value'),
                        State('measures','value'),
                        State('mapbox','relayoutData'),
                        State('mapbox','selectedData')]
                        
                    )

def dataProcess(generateCsvButton,sessionStoreData,yearSliderValue,measuresValue,relayoutData,selectedData):
    
    
    if generateCsvButton > 0:

        uniqueStations = getRedis('mapbox',sessionStoreData)


        uniqueStations = filter_by_mapbox_data(uniqueStations,relayoutData,selectedData)

        uniqueStations = list(uniqueStations['station'])

        yearBegin = yearSliderValue[0]
        yearEnd = yearSliderValue[1]

        

        dfOutput = pd.DataFrame()
        for year in range(yearBegin,yearEnd+1,1,):
            noaaFile = f's3://noaa-ghcn-pds/csv/{year}.csv'

            ddf = dd.read_csv(noaaFile,names=['ID','YEAR_MONTH_DAY','ELEMENT',
                                         'DATA_VALUE','M_FLAG','Q_FLAG','S_FLAG','OBS_TIME'],
                                         storage_options={'anon':True},header=None,
                                         dtype = {'ID':'object','YEAR_MONTH_DAY':'float64','ELEMENT':'object', 'DATA_VALUE':'int64',
                                         'M_FLAG':'object','Q_FLAG':'object','S_FLAG':'object','OBS_TIME':'float64'})

            ddfFilter = ddf[(ddf['ID'].isin(uniqueStations)) & (ddf['ELEMENT'].isin(measuresValue))]




            dfOutput = dfOutput.append(ddfFilter.compute())

            setRedis('downloadYear',year,sessionStoreData)
        


        setRedis('download',dfOutput,sessionStoreData)
        return f'You have selected {len(dfOutput):,} records.'






@app.callback(Output('progressInterval','disabled'),
            [Input('generateCsvButton','n_clicks'),
            Input('progressDivInput','children')]
             #Input('yearSlider','value')
             )
def setInterval(n_clicks,progressDivInput):
    if n_clicks > 0 and (progressDivInput is None or progressDivInput != 100):
        return False
    else:
        return True



@app.callback([Output('progressPercent','children'), Output('progressDivInput','children')],
                [Input('progressInterval','n_intervals'),
                Input('generateCsvButton','n_clicks'),
                Input('sessionStore','data')],
                [State('yearSlider','value')])
def progressUpdate(n_intervals,n_clicks,sessionStoreData,yearSliderValue):
    if n_clicks > 0:

        try:
           updateYear = getRedis('downloadYear',sessionStoreData)
           yearRange = yearSliderValue[1]-yearSliderValue[0]
           percentComplete = (updateYear-yearSliderValue[0])/yearRange * 100
           return f'{percentComplete:.0f}% Completed', percentComplete
        except:
            return '', 0  
    else:
        return None, None






























