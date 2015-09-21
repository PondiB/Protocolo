import os, shutil, re, time, subprocess, pandas, rasterio, pymongo, sys, fileinput, stat
import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import linregress
from osgeo import gdal, gdalconst

class Protocolo(object):
    
     
    '''Esta clase esta hecha para ser usada como alternativa automatizada al protocolo para tratamiento de imagenes landsat del
    Laboratorio de SIG y Teledeteccion de la Estacion Biologica de Donana. Consta de 4 metodos: Descarga, Importacion a Miramon, 
    Correccion Radiometrica y Normalizacion'''
    
    def __init__(self, ruta):
        
        
        '''Instanciamos la clase con la escena que queramos, hay que introducir la ruta a la carpeta en ori
        y de esa ruta el constructor obtiene el resto de rutas que necesita para ejecutarse'''
                
        self.ruta_escena = ruta
        self.ori = os.path.split(ruta)[0]
        self.escena = os.path.split(ruta)[1]
        self.raiz = os.path.split(self.ori)[0]
        self.geo = os.path.join(self.raiz, 'geo')
        self.rad = os.path.join(self.raiz, 'rad')
        self.nor = os.path.join(self.raiz, 'nor')
        self.mimport = os.path.join(self.ruta_escena, 'miramon_import')
        if not os.path.exists(self.mimport):
            os.makedirs(self.mimport)
        self.bat = os.path.join(self.ruta_escena, 'import.bat')
        self.bat2 = os.path.join(self.rad, 'importRad.bat')
        self.equilibrado = r'C:\Users\Diego\Desktop\Landsat_8\equilibrada.img'
        self.noequilibrado = r'C:\Users\Diego\Desktop\Landsat_8\MASK_1.img'
        self.parametrosnor = {}
        for i in os.listdir(self.ruta_escena):
            if i.endswith('MTL.txt'):
                mtl = os.path.join(self.ruta_escena,i)
                arc = open(mtl,'r')
                for i in arc:
                    if 'LANDSAT_SCENE_ID' in i:
                        usgs_id = i[-23:-2]
                    elif 'CLOUD_COVER' in i:
                        cloud_scene = float(i[-6:-1])
        arc.close()
        print "El porcentaje de nubes en la escena es de " + str(cloud_scene)
        
        self.newesc = {'_id': self.escena, 'usgs_id': usgs_id, 'cloud_scene': cloud_scene, \
                       'Info': {'Tecnico': 'LAST-EBD Auto', 'Iniciada': time.ctime(), 'Finalizada': '', \
                                  'Pasos': {'geo': '', 'rad': '', 'nor': ''}}}
        # Conectamos con MongoDB
        connection = pymongo.MongoClient("mongodb://localhost")

        # DB teledeteccion, collection landsat
        
        db=connection.teledeteccion
        landsat = db.landsat
        
        try:
        
            landsat.insert_one(self.newesc)
        
        except Exception as e:
            
            landsat.update_one({'_id':self.escena}, {'$set':{'Info.Iniciada': time.ctime()}})
            #print "Unexpected error:", type(e), e Podria dar un error por calve unica, por eso en
            #ese caso, lo que hacemos es actualizar la fecha en la que tratamos la imagen
        
    def fmask(self):
        
        '''-----\n
        Este metodo genera el algortimo Fmask que sera el que vendra por defecto en la capa de calidad de
        las landsat a partir del otono de 2015'''
        
        os.chdir(self.ruta_escena)
        print 'comenzando Fmask'
        try:
            
            t = time.time()
            os.system('C:/Cloud_Mask/Fmask 1 1 0 95')#el ultimo valor es el % de confianza sobre el pixel (nubes)
            print 'Mascara de nubes generada en ' + str(t-time.time()) + ' segundos'
                        
        except Exception as e:
            
            print e
    
    
    def mascara_cloud_pn(self):
        
        '''-----\n
        Este metodo recorta la fmask con el shp del Parque Nacional, para obtener la cobertura nubosa en Parque Nacional en el siguiente paso'''
        
        shape = r'C:\Users\Diego\Desktop\delete\donana.shp'
        crop = "-crop_to_cutline"
        
        for i in os.listdir(self.ruta_escena):
            if i.endswith('Fmask'):
                cloud = os.path.join(self.ruta_escena, i)

        cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", ]
        path_masks = os.path.join(self.ruta_escena, 'masks')
        if not os.path.exists(path_masks):
            os.makedirs(path_masks)

        
        salida = os.path.join(path_masks, 'cloud_PN.TIF')
        cmd.insert(4, shape)
        cmd.insert(5, crop)
        cmd.insert(6, cloud)
        cmd.insert(7, salida)

        proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        stdout,stderr=proc.communicate()
        exit_code=proc.wait()

        if exit_code: 
            raise RuntimeError(stderr)
                          
        
    def get_cloud_pn(self):
    
        '''-----\n
        Este metodo obtiene la cobertura de nubes sobre el Parque Nacional y lo escribe en la Base de datos'''
        
        path_masks = os.path.join(self.ruta_escena, 'masks')
        for i in os.listdir(path_masks):
            
            if i.endswith('PN.TIF'):
                
                fmask = os.path.join(path_masks, i)
                
                ds = gdal.Open(fmask)
                cloud = np.array(ds.GetRasterBand(1).ReadAsArray())
        
        mask = (cloud == 2) | (cloud == 4)
        cloud_msk = cloud[mask]
        clouds = float(cloud_msk.size)
        PN = 595713.0
        pn_cover = round((clouds/PN)*100, 2)
        ds = None
        cloud = None
        cloud_msk = None
        clouds = None
        #Insertamos la cobertura de nubes en la BD
        connection = pymongo.MongoClient("mongodb://localhost")
        db=connection.teledeteccion
        landsat = db.landsat
        
        try:
        
            landsat.update_one({'_id':self.escena}, {'$set':{'cloud_PN': pn_cover}},  upsert=True)
            
        except Exception as e:
            print "Unexpected error:", type(e), e
            
        print "El porcentaje de nubes en el Parque Nacional es de " + str(pn_cover)
        
        
    def createG_bat(self):
        
        '''-----\n
        Este metodo crea un archivo bat con los parametros necesarios para realizar la importacion'''

        #estas son las variables que necesarias para crear el bat de Miramon
        tifimg = 'C:\\MiraMon\\TIFIMG'
        num1 = '9'
        num2 = '1'
        num3 = '0'
        salidapath = self.mimport #aqui va la ruta de salida de la escena
        dt = '/DT=c:\\MiraMon'

        for i in os.listdir(self.ruta_escena):
            if i.endswith('B1.TIF'):
                banda1 = os.path.join(self.ruta_escena, i)
            elif i.endswith('MTL.txt'):
                mtl = "/MD="+self.ruta_escena+"\\"+i
            else: continue

        lista = [tifimg, num1, banda1,  salidapath, num2, num3, mtl, dt]
        print lista

        batline = (" ").join(lista)

        pr = open(self.bat, 'w')
        pr.write(batline)
        pr.close()


    def callG_bat(self):
        
        '''-----\n
        Este metodo llama ejecuta el bat de la importacion. Tarda entre 7 y 21 segundos en importar la escena'''

        #import os, time
        ti = time.time()
        a = os.system(self.bat)
        a
        if a == 0:
            print "Escena importada con exito en " + str(time.time()-ti) + " segundos"
        else:
            print "No se pudo importar la escena"
        #borramos el archivo bat creado para la importacion de la escena, una vez se ha importado esta
        os.remove(self.bat)
        
        
    def mascara_kl(self):
        
        '''-----\n
        Este metodo genera las mascaras de las zonas donde se suelen dar los kl'''
        
        lista = ['B1', 'B2', 'B3', 'B4','B5', 'B6', 'B6', 'B7', 'B9']
        shape = r'C:\Users\Diego\Desktop\Landsat_8\normalizacion l8_shapes\embalses\Emb_Clip_Ori.shp'
        crop = "-crop_to_cutline"
        path_escena = os.path.join(self.ori, self.escena)
        
        for i in os.listdir(path_escena):

            banda = i[-6:-4]

            if banda in lista:

                cmd = ["gdalwarp", "-dstnodata" , "0" , "-cutline", ]
                path_masks = os.path.join(path_escena, 'masks')
                if not os.path.exists(path_masks):
                    os.makedirs(path_masks)

                raster = os.path.join(path_escena, i)
                salida = os.path.join(path_masks, i[-6:-4]+'_mask.TIF')
                cmd.insert(4, shape)
                cmd.insert(5, crop)
                cmd.insert(6, raster)
                cmd.insert(7, salida)

                proc = subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                stdout,stderr=proc.communicate()
                exit_code=proc.wait()

                if exit_code: 
                    raise RuntimeError(stderr)
                #else: print stdout 
                    
        
    def make_hist(self):
        
        '''-----\n
        Este metodo realiza los histogramas los valores con una frecuencia acumulada por
        debajo de un valor. Los histogramas generados los guardara en rad en formato png'''
        
        path_escena = os.path.join(self.ori, self.escena)
        path_masks = os.path.join(path_escena, 'masks')
        path_rad = os.path.join(self.rad, self.escena)
        if not os.path.exists(path_rad):
            os.makedirs(path_rad)
        
        for i in os.listdir(path_masks):
                    
            if i.endswith('.TIF') and not i.startswith('cloud'):

                rs = os.path.join(path_masks, i)
                raster = gdal.Open(rs)
                banda = i[:2]

                # read raster as array
                bandraster = raster.GetRasterBand(1)
                data = bandraster.ReadAsArray()
                mask = (data != 0)
                myArray = data[mask]

                lista = sorted(myArray.tolist())
                nmask = (myArray<lista[1000])#pobar a coger los x valores mas bajos, a ver hasta cual aguanta bien
                myArray2 = myArray[nmask]

                df = pandas.DataFrame(myArray2)
                #plt.figure(); df.hist(figsize=(10,8), bins = 100)#incluir titulo y rotulos de ejes
                plt.figure(); df.hist(figsize=(10,8), bins = 50, cumulative=False, color="Red"); 
                plt.title(self.escena + '_gr_' + banda, fontsize = 18)
                plt.xlabel("Pixel Value", fontsize=16)  
                plt.ylabel("Count", fontsize=16)
                
                name = os.path.join(path_rad, self.escena + '_gr_' + banda.lower() + '.png')
                plt.savefig(name)
        
        plt.close('all')
                
                
                    
                    
    def get_kl(self):
        
        '''-----\n
        Este metodo obtiene los kl y los pasa al archivo kl de la carpeta rad'''
        
        #Hay que dejar de hacer las mascaras y simplemente aplicarlas al array
        lista_kl = []
        path_masks = os.path.join(self.ori, os.path.join(self.escena, 'masks'))
        
        for i in os.listdir(path_masks):

            if i.endswith('.TIF') and not i.startswith('cloud'):

                raster = os.path.join(path_masks, i)
                raster = gdal.Open(raster)

                # read raster as array
                bandraster = raster.GetRasterBand(1)
                arr_band = bandraster.ReadAsArray()
                mask = (arr_band != 0)
                myArray = arr_band[mask]

                #kl = myArray.min() #Asi cogeriamos el minimo de cada banda
                kl = int(np.percentile(myArray, 1)) #Asi cogemos el valor que deja por debajo el 1%
                lista_kl.append(kl)
        
        for i in os.listdir(self.rad):
            
            if i.endswith('.rad'):

                archivo = os.path.join(self.rad, i)
                dictio = {6: lista_kl[0], 7: lista_kl[1], 8: lista_kl[2], 9: lista_kl[3], \
                          10: lista_kl[4], 11: lista_kl[5], 12: lista_kl[6], 14: lista_kl[7]}

                rad = open(archivo, 'r')
                rad.seek(0)
                lineas = rad.readlines()

                for l in range(len(lineas)):

                    if l in dictio.keys():
                        lineas[l] = lineas[l].rstrip()[:-4] + str(dictio[l]) + '\n'
                    else: continue

                rad.close()

                f = open(archivo, 'w')
                for linea in lineas:
                    f.write(linea)

                f.close()
                
                src = os.path.join(self.rad, i)
                path_rad = os.path.join(self.rad, self.escena)
                if not os.path.exists(path_rad):
                    os.makedirs(path_rad)
                dst = os.path.join(path_rad, self.escena + '_kl.rad')
                shutil.copy(src, dst)
                    
        print 'modificados los metadatos del rad'
        
        
    def remove_masks(self):
        
        '''-----\n
        Este metodo elimina la carpeta en la que hemos ido guardando las mascaras empleadas para obtener los kl y
        la cobertura de nubes en el Parque Nacional'''
        
        path_masks = os.path.join(self.ruta_escena, 'masks')
        for i in os.listdir(path_masks):
            
            name = os.path.join(path_masks, i)
            os.chmod(name, stat.S_IWRITE)
            os.remove(name)

        shutil.rmtree(path_masks)
            
        
    def reproject(self):
        
        '''-----\n
        Este metodo reproyecta los geotiff originales, tomando todos los parametros que necesita para la salida, 
        extent, SCR, etc. Al mismo tiempo los cambia a formato img + hdr'''
        
        dgeo = {'B1': '_g_b1.img', 'B2': '_g_b2.img', 'B3': '_g_b3.img', 'B4': '_g_b4.img', 'B5': '_g_b5.img',\
             'B6': '_g_b6.img', 'B7': '_g_b7.img', 'B8': '_g_b8.img', 'B9': '_g_b9.img',\
           'B10': '_g_b10.img', 'B11': '_g_b11.img', 'BQA': '_g_bqa.img'}
        
        #cremos la carpeta con la ruta de destino
        destino = os.path.join(self.geo, self.escena)
        os.mkdir(destino)
        
        ti = time.time()
        #Entramos en el loop dentro de la carpeta y buscamos todos los archivos tipo .TIF
        for i in os.listdir(self.ruta_escena):

            if i.endswith('.TIF'):

                tini = time.time()
                print "Reproyectando " + i

                src_filename =  os.path.join(self.ruta_escena, i)
                src = gdal.Open(src_filename, gdalconst.GA_ReadOnly)
                src_proj = src.GetProjection()
                src_geotrans = src.GetGeoTransform()

                # De aqui tomamos los parametros que queremos que tenga la imagen de salida
                match_filename = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b5.img'
                match_ds = gdal.Open(match_filename, gdalconst.GA_ReadOnly)
                match_proj = match_ds.GetProjection()
                match_geotrans = match_ds.GetGeoTransform()
                wide = match_ds.RasterXSize
                high = match_ds.RasterYSize

                banda = None
                if len(i) == 28:
                    banda = i[-6:-4]
                else:
                    banda = i[-7:-4]
                    
                dst_filename = os.path.join(destino, self.escena + dgeo[banda])
                
                # Output 
                dst = gdal.GetDriverByName('ENVI').Create(dst_filename, wide, high, 1, gdalconst.GDT_UInt16)
                dst.SetGeoTransform(match_geotrans)
                dst.SetProjection(match_proj)
                
                # Do the work
                gdal.ReprojectImage(src, dst, src_proj, match_proj, gdalconst.GRA_Cubic)

                del dst # Flush

                print i + " reproyectada en " + str(time.time()-tini) + " segundos"
                               
            elif i.endswith('MTLFmask'):
                
                path_nor = os.path.join(self.nor, self.escena)
                if not os.path.exists(path_nor):
                    os.makedirs(path_nor)
                tini = time.time()
                print "Reproyectando " + i

                src_filename =  os.path.join(self.ruta_escena, i)
                src = gdal.Open(src_filename, gdalconst.GA_ReadOnly)
                src_proj = src.GetProjection()
                src_geotrans = src.GetGeoTransform()

                # De aqui tomamos los parametros que queremos que tenga la imagen de salida
                match_filename = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b5.img'
                match_ds = gdal.Open(match_filename, gdalconst.GA_ReadOnly)
                match_proj = match_ds.GetProjection()
                match_geotrans = match_ds.GetGeoTransform()
                wide = match_ds.RasterXSize
                high = match_ds.RasterYSize
                    
                dst_filename = os.path.join(path_nor, self.escena + '_CM.img')
                
                # Output 
                dst = gdal.GetDriverByName('ENVI').Create(dst_filename, wide, high, 1, gdalconst.GDT_UInt16)
                dst.SetGeoTransform(match_geotrans)
                dst.SetProjection(match_proj)

                # Do the work
                gdal.ReprojectImage(src, dst, src_proj, match_proj, gdalconst.GRA_Cubic)

                del dst # lush
                
        print "Reproyeccion completa realizada en " + str((time.time()-ti)/60) + " minutos"
        
        
    def copyDocG(self):
        
        '''-----\n
        Este metodo copia los doc y el rel generados por Miramon al importar la imagen y los pasa a geo'''

        rutageo = os.path.join(self.geo, self.escena)
        for i in os.listdir(self.mimport):
    
            d = {'B1-CA': '_g_b1', 'B10-LWIR1': '_g_b10', 'B11-LWIR2': '_g_b11', 'B2-B': '_g_b2', 'B3-G': '_g_b3', 'B4-R': '_g_b4', 'B5-NIR': '_g_b5', 'B6-SWIR1': '_g_b6', 'B7-SWIR2': '_g_b7',\
                'B8-PAN': '_g_b8', 'B9-CI': '_g_b9', 'BQA-CirrusConfidence': '_g_BQA-Cirrus', 'BQA-CloudConfidence': '_g_BQA-Cloud', 'BQA-DesignatedFill': '_g_BQA-DFill',\
                'BQA-SnowIceConfidence': '_g_BQA-SnowIce', 'BQA-TerrainOcclusion': '_g_BQA-Terrain', 'BQA-WaterConfidence': '_g_BQA-Water'}

            if i.endswith('.doc'):
                
                number = i[20:-7]
                key = d[number]
                src = os.path.join(self.mimport, i)
                dst = os.path.join(rutageo, self.escena + key + '.doc')
                shutil.copy(src, dst)
            elif i.endswith('.rel'):
                
                src = os.path.join(self.mimport, i)
                dst = os.path.join(rutageo, self.escena + '_g_' + i[-6:])
                shutil.copy(src, dst)
            else: continue
                
        print 'Archivos doc y rel copiados a geo'
                
    def modifyDocG(self):
        
        '''-----\n
        Este metodo edita los doc copiados a geo para que tenga los valores correctos'''
        
        ruta = os.path.join(self.geo, self.escena)
        for i in os.listdir(ruta):
        
            if i.endswith('.doc'):

                archivo = os.path.join(ruta, i)

                doc = open(archivo, 'r')
                doc.seek(0)
                lineas = doc.readlines()

                for l in range(len(lineas)):

                    if lineas[l].startswith('columns'):
                        lineas[l] = 'columns     : 8734\n'
                    elif lineas[l].startswith('rows'):
                        lineas[l] = 'rows        : 7734\n'
                    elif lineas[l].startswith('min. X'):
                        lineas[l] = 'min. X      : 78000.0000000000\n'
                    elif lineas[l].startswith('max. X'):
                        lineas[l] = 'max. X      : 340020.000000000\n'
                    elif lineas[l].startswith('min. Y'):
                        lineas[l] = 'min. Y      : 4036980.00000000\n'
                    elif lineas[l].startswith('max. Y'):
                        lineas[l] = 'max. Y      : 4269000.00000000\n'
                    elif lineas[l].startswith('ref. system'):
                        lineas[l] = 'ref. system : UTM-30N-PS\n'
                    else: continue

                doc.close()

                f = open(archivo, 'w')
                for linea in lineas:
                    f.write(linea)

                f.close()
                print 'modificados los metadatos de ', i
                
                
    def modifyRelG(self):
        
        '''-----\n
        Este metodo modifica el rel de geo para que tenga los valores correctos'''
        
        process = '\n[QUALITY:LINEAGE:PROCESS2]\nnOrganismes=1\nhistory=reproyeccion\npurpose=reproyeccion por convolucion cubica\ndate=' + str(time.strftime("%Y%m%d %H%M%S00")) + '\n'
        tech = '\n[QUALITY:LINEAGE:PROCESS2:ORGANISME_1]\nIndividualName=Auto Protocol Proudly made by Diego Garcia Diaz\nPositionName=Tecnico LAST\nOrganisationName=(CSIC) LAST-EBD (APP)\n'
        pro = process + tech + '\n'
        
        ruta = os.path.join(self.geo, self.escena)
        for i in os.listdir(ruta):
            if i.endswith('rel'):
                rel_file = os.path.join(ruta, i)
        
        rel = open(rel_file, 'r')
        lineas = rel.readlines()
        
        dgeo = {'B1-CA': '_g_b1', 'B10-LWIR1': '_g_b10', 'B11-LWIR2': '_g_b11', 'B2-B': '_g_b2', 'B3-G': '_g_b3', 'B4-R': '_g_b4', 'B5-NIR': '_g_b5', 'B6-SWIR1': '_g_b6', 'B7-SWIR2': '_g_b7',\
                'B8-PAN': '_g_b8', 'B9-CI': '_g_b9', 'BQA-CirrusConfidence': '_g_BQA-Cirrus', 'BQA-CloudConfidence': '_g_BQA-Cloud', 'BQA-DesignatedFill': '_g_BQA-DFill',\
                'BQA-SnowIceConfidence': '_g_BQA-SnowIce', 'BQA-TerrainOcclusion': '_g_BQA-Terrain', 'BQA-WaterConfidence': '_g_BQA-Water'}
        
        for l in range(len(lineas)):
    
            if lineas[l].rstrip() == '[EXTENT]':
                lineas[l-1] = pro
            elif lineas[l].startswith('FileIdentifier'):
                lineas[l] = 'FileIdentifier='+ self.escena + '_g_' + lineas[l][-9:]
            elif lineas[l].startswith('IndividualName'):
                lineas[l] = 'IndividualName=Digd_Geo\n'
            elif lineas[l].startswith('PositionName'):
                lineas[l] = 'PositionName=Tecnico GIS-RS LAST-EBD\n'
            elif lineas[l].startswith('columns'):
                lineas[l] = 'columns=8734\n'
            elif lineas[l].startswith('rows'):
                lineas[l] = 'rows=7734\n'
            elif lineas[l].startswith('MinX'):
                lineas[l] = 'MinX=78000\n'
            elif lineas[l].startswith('MaxX'):
                lineas[l] = 'MaxX=340020\n'
            elif lineas[l].startswith('MinY'):
                lineas[l] = 'MinY=4036980\n'
            elif lineas[l].startswith('MaxY'):
                lineas[l] = 'MaxY=4269000\n'
            elif lineas[l].startswith('max. Y'):
                lineas[l] = 'MinY=4036980\n'  
            elif lineas[l].startswith('HorizontalSystemIdentifier'):
                lineas[l] = 'HorizontalSystemIdentifier=UTM-30N-PS\n'
            elif lineas[l].startswith('IndexsNomsCamps'):
                lineas[l] = 'IndexsNomsCamps=1-CA,2-B,3-G,4-R,5-NIR,6-SWIR1,7-SWIR2,9-CI\n'
            elif lineas[l].startswith('NomFitxer=LC8_202034'):
                bandname = lineas[l][30:-8]
                lineas[l] = 'NomFitxer='+self.escena+dgeo[bandname]+'.img\n'
            elif lineas[l] == '[ATTRIBUTE_DATA:8-PAN]\n':
                start_b8 = l
            elif lineas[l] == '[ATTRIBUTE_DATA:9-CI]\n':
                end_b8 = l
            elif lineas[l].startswith('NomCamp_10-LWIR1=10-LWIR1'):
                start_band_name = l
            elif lineas[l].startswith('NomCamp_17=QA-CloudConfidence'):
                end_band_name = l+1
            elif lineas[l].startswith('[ATTRIBUTE_DATA:10-LWIR1]'):
                start_end = l
            else: continue
                
        rel.close()

        new_list = lineas[:start_band_name]+lineas[end_band_name:start_b8]+lineas[end_b8:start_end]
        new_list.remove('NomCamp_8-PAN=8-PAN\n')
        
        f = open(rel_file, 'w')
        for linea in new_list:
            f.write(linea)

        f.close()
            
            
    def copy_files_GR(self):
        
        '''-----\n
        Este metodo copia las bandas de 1 a 9 de geo a rad, para proceder a la correccion radiometrica'''

        lista_bandas = ['b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7', 'b9']

        path_escena_geo =  os.path.join(self.geo, self.escena)
        path_escena_rad =  os.path.join(self.rad, self.escena)
        if not os.path.exists(path_escena_rad):
            os.makedirs(path_escena_rad)

        for i in os.listdir(path_escena_geo):

            banda = i[-6:-4]

            if banda in lista_bandas:

                src = os.path.join(path_escena_geo, i)
                dst = os.path.join(path_escena_rad, i)   
                shutil.copy(src, dst)

            elif i.endswith('.rel'):

                src = os.path.join(path_escena_geo, i)
                dst = os.path.join(path_escena_rad, i)
                shutil.copy(src, dst)

            else: continue

        print 'Archivos copiados y renombrados a Rad'
           
                
    def createR_bat(self):
        
        '''-----\n
        Este metodo crea el bat para realizar la correcion radiometrica'''

        #Incluimos reflectividades por arriba y por debajo de 100 y 0
        path_escena_rad = os.path.join(self.rad, self.escena)
        corrad = 'C:\MiraMon\CORRAD'
        num1 = '1'
        dtm = os.path.join(self.rad, 'sindato.img')
        kl = os.path.join(self.rad, 'kl.rad')
        #REF_SUP y REF_INF es xa el ajuste o no a 0-100, mirar si se quiere o no
        string = '/MULTIBANDA /CONSERVAR_MDT /LIMIT_LAMBERT=73.000000 /REF_SUP_100 /REF_INF_0 /DT=c:\MiraMon'

        for i in os.listdir(os.path.join(self.rad, self.escena)):
            if i.endswith('b1.img'):
                banda1 = os.path.join(path_escena_rad, i)
            else: continue

        lista = [corrad, num1, banda1, path_escena_rad,  dtm, kl, string]
        print lista

        batline = (" ").join(lista)

        pr = open(self.bat2, 'w')
        pr.write(batline)
        pr.close()


    def callR_bat(self):

        '''-----\n
        Este metodo ejecuta el bat que realiza la correcion radiometrica'''
        
        ti = time.time()
        print 'Llamando a Miramon... Miramon!!!!!!'
        a = os.system(self.bat2)
        a
        if a == 0:
            print "Escena corregida con exito en " + str(time.time()-ti) + " segundos"
        else:
            print "No se pudo realizar la correccion de la escena"
        #borramos el archivo bat creado para la importacion de la escena, una vez se ha importado esta
        os.remove(self.bat2)
        
        
    def cleanR(self):
        
        '''-----\n
        Este metodo borra los archivos copiados de geo, de modo que nos quedamos solo con los hdr y los img y doc generado 
        por el Corrad, junto con los png de los histogramas'''         
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        
        #Copiamos el rel tal y como sale del Corrad
        for i in os.listdir(path_escena_rad):
            if i.startswith('r_') and i.endswith('.rel'):
                rel = os.path.join(path_escena_rad, i)
                rel_txt = os.path.join(path_escena_rad, 'rel_original_values.txt')
                shutil.copy(rel, rel_txt)                         
        #Borramos los archivos que no hacen falta
        for i in os.listdir(path_escena_rad):
            if not i.startswith('r_'):
                if not i.endswith('.hdr'):
                    if not i.endswith('.png'):
                        if not i.endswith('.rad'):
                            if not i.endswith('.txt'):
                                os.remove(os.path.join(path_escena_rad, i))
            elif i.startswith('r_'):
                src = os.path.join(path_escena_rad, i)
                dst = os.path.join(path_escena_rad, i[2:23]+'r'+i[-7:])
                os.rename(src, dst)
        #hdrs
        for i in os.listdir(path_escena_rad):
            if i.endswith('.hdr'):
                src = os.path.join(path_escena_rad, i)
                dst = os.path.join(path_escena_rad, i[:21]+'r'+i[-7:])
                os.rename(src, dst)
            
    
    def correct_sup_inf(self):
        
        '''-----\n
        Este metodo soluciona el problema de los pixeles con alta y baja reflectividad, llevando los bajos a valor 1 
        y los altos a 254'''
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_escena_rad):
       
            if i.endswith('.img'):
                
                banda = os.path.join(path_escena_rad, i)
                outfile = os.path.join(path_escena_rad, 'crt_' + i)
                
                with rasterio.drivers():
                    with rasterio.open(banda) as src:
                        rs = src.read()
                        mini = (rs == rs.min())
                        min_msk = (rs>rs.min()) & (rs<=0)
                        max_msk = (rs>=100)
                        rs[min_msk] = 0
                        rs[max_msk] = 100.0
                        rs[mini] = 255
                        
                        profile = src.meta
                        profile.update(dtype=rasterio.float32)

                        with rasterio.open(outfile, 'w', **profile) as dst:
                            dst.write(rs.astype(rasterio.float32))
                            
    def clean_correct_R(self):
        
        '''-----\n
        Este metodo borra los archivos resultantes del Corrad antes de hacer 
        la correccion de reflectividades altas y bajas''' 
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_escena_rad):
            if (i.endswith('.img')| i.endswith('.hdr')) and not i.startswith('crt'):
                os.remove(os.path.join(path_escena_rad, i))
                
        for i in os.listdir(path_escena_rad):
            if i.endswith('aux.xml'):
                os.remove(os.path.join(path_escena_rad, i))
        
        for i in os.listdir(path_escena_rad):
            if i.endswith('.img')| i.endswith('.hdr'):
                src = os.path.join(path_escena_rad, i)
                dst = os.path.join(path_escena_rad, i[4:])
                os.rename(src,dst)
                
                
    def modify_hdr_rad(self): #QUITAR DEL CORRAD. En principio ya no va a hacer falta, en odo caso se podria usar xa insertar el IgnoreValue
        
        '''-----\nEste metodo edita los hdr para que tengan el valor correcto (FLOAT) para poder ser entendidos por GDAL.
        Hay que ver si hay que establecer primero el valor como No Data'''
                
        path_escena_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_escena_rad):
        
            if i.endswith('.hdr'):

                archivo = os.path.join(path_escena_rad, i)
                hdr = open(archivo, 'r')
                hdr.seek(0)
                lineas = hdr.readlines()
                for l in range(len(lineas)):
                    if l == 8:
                        lineas[l] = 'data type = 4\n'
                lineas.append('data ignore value = -3.40282347e+38') 
                 
                hdr.close()

                f = open(archivo, 'w')
                for linea in lineas:
                    f.write(linea)

                f.close()
                print 'modificados los metadatos de ', i
                
    def modify_hdr_rad_255(self): 
        
        '''-----\n
        Este metodo edita los hdr para que tengan el valor correcto (FLOAT) para poder ser entendidos por GDAL.
        Hay que ver si hay que establecer primero el valor como No Data'''
                
        path_escena_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_escena_rad):
        
            if i.endswith('.hdr'):

                archivo = os.path.join(path_escena_rad, i)
                hdr = open(archivo, 'r')
                hdr.seek(0)
                lineas = hdr.readlines()
                for l in range(len(lineas)):
                    if l == 8:
                        lineas[l] = 'data type = 4\n'
                lineas.append('data ignore value = 255') 
                 
                hdr.close()

                f = open(archivo, 'w')
                for linea in lineas:
                    f.write(linea)

                f.close()
                print 'modificados los metadatos de ', i
                
    def translate_bytes_gdal(self):
    
        '''-----\n
        Este metodo hace la conversion de reales (float32) a byte'''
        
        path_escena_rad = os.path.join(self.rad, self.escena)
        path_escena_rad_byte = os.path.join(path_escena_rad, 'byte')
        if not os.path.exists(path_escena_rad_byte):
            os.makedirs(path_escena_rad_byte)
        
        cmd = "gdal_translate -ot Byte -of ENVI -scale 0 100 0 254 -a_nodata 255"

        for i in os.listdir(path_escena_rad):

            if i.endswith('img'):

                input_rs = os.path.join(path_escena_rad, i)
                output_rs = os.path.join(path_escena_rad_byte, i)

                lst = cmd.split()
                lst.insert(12, input_rs)
                lst.insert(13, output_rs)

                proc = subprocess.Popen(lst,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                stdout,stderr=proc.communicate()
                exit_code=proc.wait()

                if exit_code: 
                    raise RuntimeError(stderr)
                else: 
                    print stdout 
                
           
    def modifyRelRad(self):
        
        '''-----\n
        Este metodo modifica el rel de rad para que tenga los valores correctos'''
        
        path_geo = os.path.join(self.geo, self.escena)
        path_rad = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_geo):
            if i.endswith('rel'):
                rel_file_geo = os.path.join(path_geo, i)
    
        rel_geo = open(rel_file_geo, 'r')
        lineasgeo = rel_geo.readlines()
        for i in range(len(lineasgeo)):
            if lineasgeo[i] == '[QUALITY:LINEAGE:PROCESS1]\n':
                start = i
                end = start + 21

        pro = lineasgeo[start:end]         
        pros = '\n'+''.join(pro)

        for i in os.listdir(path_rad):
            if i.endswith('rel'):
                rel_file = os.path.join(path_rad, i)

        for line in fileinput.input(rel_file, inplace = 1): 
            print line.replace("PROCESS1", "PROCESS3"),
        for line in fileinput.input(rel_file, inplace = 1): 
            print line.replace("-3.4028235E+38", "255"),
        for line in fileinput.input(rel_file, inplace = 1): 
            print line.replace("%", "Refs(%)*254"),
        for line in fileinput.input(rel_file, inplace = 1): 
            print line.replace("processes=1", "processes=1,2,3"),


        rel = open(rel_file, 'r')
        lineas = rel.readlines()

        drad = {'b1': '_gr_b1.img', 'b2': '_gr_b2.img', 'b3': '_gr_b3.img', 'b4': '_gr_b4.img', 'b5': '_gr_b5.img','b6': '_gr_b6.img', 'b7': '_gr_b7.img', 'b8': '_gr_b8.img', 'b9': '_gr_b9.img'}

        for l in range(len(lineas)):

            if lineas[l].startswith('NomFitxer=r_'):
                bandname = lineas[l][-7:-5]
                lineas[l] = lineas[l][:10] + '20150518l8202_34' + drad[bandname]+'\n'
            elif lineas[l] == 'resolution=30\n':
                pos = l+1
            elif lineas[l].startswith('TipusCompressio'):
                lineas[l] = 'TipusCompressio=byte\n'
            elif lineas[l].startswith('ToneGradation'):
                lineas[l]='ToneGradation=255\n'            
            elif lineas[l].startswith('BitsPerValue'):
                lineas[l]='BitsPerValue=8\n'
            elif lineas[l].startswith('min='):
                lineas[l]='min=0\n'
            elif lineas[l].startswith('max='):
                lineas[l]='max=254\n'
            
        lineas.insert(pos, pros)
        rel.close()

        f = open(rel_file, 'w')
        for linea in lineas:
            f.write(linea)

        f.close()
        
        
    def re_clean_R(self):
        
        '''-----\n
        Este metodo borra las bandas procedentes de la primera correcion de las bandas en float32
        (para solucionar los valores de altas y bajas reflectividades).Se borran los img y hdr de la
        escena en byte, y se copian desde byte las bandas ya reescaladas, finalmente se borra la carpeta byte'''
        
        path_rad = os.path.join(self.rad, self.escena)
        path_rad_byte = os.path.join(path_rad, 'byte')
        
        #borramos los img y hdr reclasificados pero aun en porcentaje
        for i in os.listdir(path_rad):

            if i.endswith('.img') or i.endswith('hdr'):
                files = os.path.join(path_rad, i)
                os.remove(files)
            #else: continue
        
        #copiamos los hdr y los img de byte a la  carpeta de la escena en rad
        for i in os.listdir(path_rad_byte):

            if i.endswith('.img') or i.endswith('hdr'):
                src = os.path.join(path_rad_byte, i)
                dst = os.path.join(path_rad, i)
                os.rename(src, dst)
            #else: continue
                                
        #borramos la carpeta byte con los xml que quedan en ella
        for i in os.listdir(path_rad):
            fold = os.path.join(path_rad, i)
            if os.path.isdir(fold):
                shutil.rmtree(fold)
            
                
    def modifyDocR(self):
        
        '''-----\n
        Este metodo edita los doc de rad para que tengan los valores correctos'''
        
        path_rad = os.path.join(self.rad, self.escena)
                                
        for i in os.listdir(path_rad):
        
            if i.endswith('.doc'):

                archivo = os.path.join(path_rad, i)

                doc = open(archivo, 'r')
                doc.seek(0)
                lineas = doc.readlines()

                for l in range(len(lineas)):

                    if lineas[l].startswith('data type'):
                        lineas[l] = 'data type   : byte\n'
                    elif lineas[l].startswith('value units'):
                        lineas[l] = 'value units : Refs(%)*254\n'
                    elif lineas[l].startswith('flag value'):
                        lineas[l] = 'flag value  : 255\n'
                    elif lineas[l].startswith('min. value'):
                        lineas[l] = 'min. value  : 0\n'
                    elif lineas[l].startswith('max. value'):
                        lineas[l] = 'max. value  : 254\n'
                    else: continue

                doc.close()

                f = open(archivo, 'w')
                for linea in lineas:
                    f.write(linea)

                f.close()
                print 'modificados los metadatos de ', i
                                
                                
    def normalize(self):
        
        '''-----\n
        Este metodo controlo el flujo de la normalizacion, si no se llegan a obtener los coeficientes (R>0.85 y N_Pixeles >= 10,
        va pasando hacia el siguiente nivel, hasta que se logran obtener esos valores o hasta que se llega al ultimo paso)'''
        path_rad_escena = os.path.join(self.rad, self.escena)
                
        bandasl8 = ['b2', 'b3', 'b4', 'b5', 'b6', 'b7']
        bandasl7 = ['b1', 'b2', 'b3', 'b4', 'b5', 'b7']
        
        if 'l7' in self.escena:
            print 'landsat 7\n'
            lstbandas = bandasl7
        else:
            print 'landsat 8\n'
            lstbandas = bandasl8
            
        for i in os.listdir(path_rad_escena):
            
            banda = os.path.join(path_rad_escena, i)
            banda_num = banda[-6:-4]
            if banda_num in lstbandas and i.endswith('.img'):
                
                print banda, ' desde normalize'
                self.nor1(banda, self.noequilibrado)
                #Esto es un poco feo, pero funciona. Probar a hacerlo con una lista de funciones
                if banda_num not in self.parametrosnor.keys():
                    self.nor1(banda, self.noequilibrado, std = 22)
                    if banda_num not in self.parametrosnor.keys():
                        self.nor1(banda, self.equilibrado)
                        if banda_num not in self.parametrosnor.keys():
                            self.nor1(banda, self.equilibrado, std = 22)
                            if banda_num not in self.parametrosnor.keys():
                                self.nor1(banda, self.noequilibrado, std = 33)
                                if banda_num not in self.parametrosnor.keys():
                                    self.nor1(banda, self.noequilibrado, std = 33)
                                else:
                                    print 'No se ha podido normalizar la banda ', banda_num
                                    
            #Una vez acabados los bucles guardamos los coeficientes en un txt. Redundante pero asi hay 
            #que hacerlo porque quiere David
            path_nor = os.path.join(self.nor, self.escena)
            if not os.path.exists(path_nor):
                os.makedirs(path_nor)
            arc = os.path.join(path_nor, 'coeficientes.txt')
            f = open(arc, 'w')
            for i in sorted(b.parametrosnor.items()):
                f.write(str(i)+'\n')
            f.close()  
            
            #Insertamos los datos en la MongoDB (que es lo que mola, y no tanto txt ;))
            connection = pymongo.MongoClient("mongodb://localhost")
            db=connection.teledeteccion
            landsat = db.landsat

            try:

                landsat.update_one({'_id':self.escena}, {'$set':{'Info.Pasos.nor': 
                                    {'Normalize': 'True', 'Nor-Values': self.parametrosnor, 'Fecha': time.ctime()}}})

            except Exception as e:
                print "Unexpected error:", type(e), e
                
    def nor1(self, banda, mascara, std = 11):
        
        '''-----\n
        Este metodo busca obtiene los coeficientes necesarios para llevar a cabo la normalizacion,
        tanto en nor1 como en nor1bis'''

        print 'comenzando nor1'
        
        #Ruta a las bandas usadas para normalizar
        path_b1 = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b1.img'
        path_b2 = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b2.img'
        path_b3 = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b3.img'
        path_b4 = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b4.img'
        path_b5 = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b5.img'
        path_b7 = r'C:\Users\Diego\Desktop\Landsat_8\20020718l7etm202_34\20020718l7etm202_34_grn1_b7.img'
        
        dnorbandasl8 = {'b2': path_b1, 'b3': path_b2, 'b4': path_b3, 'b5': path_b4, 'b6': path_b5, 'b7': path_b7}
        dnorbandasl7 = {'b1': path_b1, 'b2': path_b2, 'b3': path_b3, 'b4': path_b4, 'b5': path_b5, 'b7': path_b7}
        
        if 'l7' in self.escena:
            dnorbandas = dnorbandasl7
        else:
            dnorbandas = dnorbandasl8
            
        path_nor = os.path.join(self.nor, self.escena)
        for i in os.listdir(path_nor):
            
            if i.endswith('CM.img'):
                mask_nubes = os.path.join(path_nor, i)
                print mask_nubes
                    
        if mascara == self.noequilibrado:
            poly_inv_tipo = r'C:\Users\Diego\Desktop\Landsat_8\pol_inv_tipo.img'
        else:
            poly_inv_tipo = r'C:\Users\Diego\Desktop\Landsat_8\pol_inv_2_tipo.img'

        print 'mascara: ', mascara
        
        with rasterio.open(mascara) as src:
            mask1 = src.read()
        with rasterio.open(mask_nubes) as src:
            cloud = src.read()
        with rasterio.open(poly_inv_tipo) as src:
            pias = src.read()

        banda_num = banda[-6:-4]
        print banda_num
        if banda_num in dnorbandas.keys():
            with rasterio.open(banda) as src:
                current = src.read()
            #Aqui con el diccionario nos aseguramos de que estamos comparando cada banda con su homologa del 20020718
            with rasterio.open(dnorbandas[banda_num]) as src:
                ref = src.read()
            #Ya tenemos todas las bandas de la imagen actual y de la imagen de referencia leidas como array

            #Aplicamos la mascara de las PIAs
            mask_curr_pia = np.ma.masked_where(mask1!=1,current)
            mask_ref_pia = np.ma.masked_where(mask1!=1,ref)
            mask_pias = np.ma.masked_where(mask1!=1,pias)
            cloud_pias = np.ma.masked_where(mask1!=1,cloud)
            #hemos aplicado la mascara y ahora guardamos una nueva matriz con la mascara aplicamos
            ref_PIA = np.ma.compressed(mask_ref_pia)
            current_PIA = np.ma.compressed(mask_curr_pia)
            pias_PIA = np.ma.compressed(mask_pias)
            cloud_PIA = np.ma.compressed(cloud_pias)

            #Aplicamos la mascara de NoData
            NoData_current_mask = np.ma.masked_where(current_PIA==255,current_PIA)
            NoData_ref_mask = np.ma.masked_where(current_PIA==255,ref_PIA)
            NoData_pias_mask = np.ma.masked_where(current_PIA==255,pias_PIA)
            NoData_cloud_mask = np.ma.masked_where(current_PIA==255,cloud_PIA)
            ref_PIA_NoData = np.ma.compressed(NoData_ref_mask)
            current_PIA_NoData = np.ma.compressed(NoData_current_mask)
            pias_PIA_NoData = np.ma.compressed(NoData_pias_mask)
            cloud_PIA_NoData = np.ma.compressed(NoData_cloud_mask)
            
            #Aplicamos la mascara de Nubes
            cloud_current_mask = np.ma.masked_where((cloud_PIA_NoData==2)|(cloud_PIA_NoData==4),current_PIA_NoData)
            cloud_ref_mask = np.ma.masked_where((cloud_PIA_NoData==2)|(cloud_PIA_NoData==4),ref_PIA_NoData)
            cloud_pias_mask = np.ma.masked_where((cloud_PIA_NoData==2)|(cloud_PIA_NoData==4),pias_PIA_NoData)
            
            ref_PIA_Cloud_NoData = np.ma.compressed(cloud_ref_mask)
            current_PIA_Cloud_NoData = np.ma.compressed(cloud_current_mask)
            pias_PIA_Cloud_NoData = np.ma.compressed(cloud_pias_mask)
            

            #Realizamos la 1 regresion
            slope, intercept, r_value, p_value, std_err = linregress(current_PIA_Cloud_NoData,ref_PIA_Cloud_NoData)
            #print '1 regresion: slope: '+ str(slope), 'intercept:', intercept, 'r', r_value, 'N:', len(ref_PIA_NoData)

            #Ahora tenemos los parametros para obtener el residuo de la primera regresion y 
            #eliminar aquellos que son mayores de abs(11.113949)
            esperado = current_PIA_Cloud_NoData * slope + intercept
            residuo = ref_PIA_Cloud_NoData - esperado

            mask_current_PIA_NoData_STD = np.ma.masked_where(abs(residuo)>=int(std), current_PIA_Cloud_NoData)
            mask_ref_PIA_NoData_STD = np.ma.masked_where(abs(residuo)>=int(std),ref_PIA_Cloud_NoData)
            mask_pias_PIA_NoData_STD = np.ma.masked_where(abs(residuo)>=int(std),pias_PIA_Cloud_NoData)
            current_PIA_NoData_STD = np.ma.compressed(mask_current_PIA_NoData_STD)
            ref_PIA_NoData_STD = np.ma.compressed(mask_ref_PIA_NoData_STD)
            pias_PIA_NoData_STD = np.ma.compressed(mask_pias_PIA_NoData_STD)

            #Hemos enmascarado los resiudos, ahora calculamos la 2 regresion
            slope, intercept, r_value, p_value, std_err = linregress(current_PIA_NoData_STD,ref_PIA_NoData_STD)
            print '\n++++++++++++++++++++++++++++++++++'
            print 'slope: '+ str(slope), 'intercept:', intercept, 'r', r_value, 'N:', len(ref_PIA_NoData_STD)
            print '++++++++++++++++++++++++++++++++++\n'

            #Los parametros estan ok, pero hay que hacer las mascaras de cada area PIA para ver el count
            values = {}
            values_str = {1: 'Mar', 2: 'Embalses', 3: 'Pinar', 4: 'Urbano-1', 5: 'Urbano-2', 6: 'Aeropuertos', 7: 'Arena', 8: 'Pastizales', 9: 'Mineria'}
            for i in range(1,10):
                mask_pia_= np.ma.masked_where(pias_PIA_NoData_STD != i, pias_PIA_NoData_STD)
                PIA = np.ma.compressed(mask_pia_)
                a = PIA.tolist()
                values[i] = len(a)
            #pasamos las claves de cada zona a string
            for i in values.keys():
                values[values_str[i]] = values.pop(i)
            print values,  #imprime el count de pixeles xa cada zona
            print banda_num
            #Generamos el raster de salida despues de aplicarle la ecuacion de regresion. Esto seria el nor2
            #Por aqui hay que ver como se soluciona
            if r_value > 0.85 and min(values.values()) >= 10:
                self.parametrosnor[banda_num]= {'Parametros':{'slope': slope, 'intercept': intercept, 'r': r_value, 'N': len(ref_PIA_NoData_STD)}, 
                                                'Tipo_Area': values}
                
                print 'parametros en nor1: ', self.parametrosnor
                print '\comenzando nor2\n'
                self.nor2l8(banda, slope, intercept)#llamamos a nor2, Tambien funciona con L7
                print '\nNormalizacion de ', banda_num, ' realizada.\n'
            else:
                pass
                                       
                    
    def nor2l8(self, banda, slope, intercept):
    
        '''-----\n
        Este metodo aplica la ecuacion de la recta de regresion a cada banda (siempre que los haya podido obtener), y posteriormente
        reescala los valores para seguir teniendo un byte (0-255)'''
          
        path_nor_escena = os.path.join(self.nor, self.escena)
        if not os.path.exists(path_nor_escena):
            os.makedirs(path_nor_escena)
        banda_num = banda[-6:-4]
        outFile = os.path.join(path_nor_escena, self.escena + '_grn1_' + banda_num + '.img')
        
        with rasterio.drivers():
            
            with rasterio.open(banda) as src:
                rs = src.read()

                #NoData_rs = np.ma.masked_where(rs==255,rs)
                rs = rs*slope+intercept
                
                #nd = (rs <= rs.min())
                min_msk =  (rs < 0)             #(rs>rs.min()+0.1) & (rs<0.5)
                max_msk = (rs>=255)
                #rs[nd] = 255
                rs[min_msk] = 0
                rs[max_msk] = 255
                
                rs = np.around(rs)

                profile = src.meta
                profile.update(dtype=rasterio.uint8)

                with rasterio.open(outFile, 'w', **profile) as dst:
                    dst.write(rs.astype(rasterio.uint8))
    
    def copyDocR(self):
        
        '''-----\n
        Este metodo copia los doc y el rel generados por Miramon al hacer el Corrad y los pasa a nor'''

        path_rad = os.path.join(self.rad, self.escena)
        path_nor = os.path.join(self.nor, self.escena)
        
        for i in os.listdir(path_rad):
    
           if i.endswith('.doc') | i.endswith('.rel'):
               
                if 'b1' not in i and 'b9' not in i:
                
                    src = os.path.join(path_rad, i)
                    dst = os.path.join(path_nor, i)
                    shutil.copy(src, dst)
                
        for i in os.listdir(path_nor):
            
            if i.endswith('.doc') | i.endswith('.rel'):
                src = os.path.join(path_nor, i)
                dst = os.path.join(path_nor, i.replace('_gr_', '_grn1_'))
                os.rename(src, dst)
                            
        print 'Archivos doc y rel copiados a nor'
        
    def modifyRelNor(self):
        
        '''-----\n
        Este metodo modifica el rel de nor para que tenga los valores correctos'''
        
        process = '[QUALITY:LINEAGE:PROCESS4]\nnOrganismes=1\nhistory=Creada con Auto Protocol (Python). Normalizacion banda a banda mediante regresion lineal. Parametros de calibracion (offset y gain) en el fichero coeficientes.txt de la escena en nor Paraetros calculados mediante regresion por minimos cuadrados partiendo de 60561 pixeles pseudoinvariantes definidos en 80 poligonos de 9 tipos (desde mar hasta arenas, ver tambien coeficientes.xt). Se eliminan nubes, valores perdidos y pixeles que cambian mas del 11,22, o 33 stds. Ver procedimiento detallado en la clase Protocolo (self.normalizacion). Imagen de referencia 20020718l7etm202_34_gr.\npurpose=Normalizacion radiometrica de la serie temporal\ndate=' + str(time.strftime("%Y%m%d %H%M%S00")) + '\n'
        tech = '\n[QUALITY:LINEAGE:PROCESS4:ORGANISME_1]\nIndividualName=Auto Protocol Proudly made by Diego Garcia Diaz\nPositionName=Tecnico LAST\nOrganisationName=(CSIC) LAST-EBD (APP)\n'
        pro = process + tech + '\n'
        
        #Buscamos el rel, lo abrimos en modo lectura y buscamos la linea donde queremos insertar el texto
        path_nor = os.path.join(self.nor, self.escena)
        
        for i in os.listdir(path_nor):
            if i.endswith('rel'):
                rel_file = os.path.join(path_nor, i)
        
        for line in fileinput.input(rel_file, inplace = 1): 
            print line.replace("_gr_", "_grn1_"),  
        for line in fileinput.input(rel_file, inplace = 1): 
            print line.replace("processes=1,2,3", "processes=1,2,3,4"),
        for line in fileinput.input(rel_file, inplace = 1): 
            print line.replace("IndexsNomsCamps=1-CA,2-B,3-G,4-R,5-NIR,6-SWIR1,7-SWIR2,9-CI", "IndexsNomsCamps=2-B,3-G,4-R,5-NIR,6-SWIR1,7-SWIR2"),
        
        rel_nor = open(rel_file, 'r')
        lineas = rel_nor.readlines()
        for i in range(len(lineas)):
            if lineas[i] == '[QUALITY:LINEAGE]\n':
                pos = i
                            
        #insertamos el texto
        lineas.insert(pos, pro)
        
        #Ahora cambiamos el nombre a las bandas e incluimos el proceso 4 en el quality linage process
        
            
        #Cerramos el rel
        rel_nor.close()
        
        for i in range(len(lineas)):
            if lineas[i] == '[ATTRIBUTE_DATA:1-CA]\n':
                start_b1 = i
            elif lineas[i] == '[ATTRIBUTE_DATA:2-B]\n':
                start_b2 = i
            elif lineas[i] == '[ATTRIBUTE_DATA:9-CI]\n':
                start_b9 = i
        
        new_lineas = lineas[:start_b1] + lineas[start_b2:start_b9]
                
                
        for i in range(len(new_lineas)-2):
            if new_lineas[i].startswith('NomCamp_1') or new_lineas[i].startswith('NomCamp_9'):
                        new_lineas.remove(new_lineas[i])
            
        #Abrimos el rel en modo escritura y le pasamos las lineas con el proceso 4 ya insertado como argumento
        f = open(rel_file, 'w')
        for linea in new_lineas:
            f.write(linea)
        #Cerramos y a otra cosa mariposa
        f.close()
        
        
    def fmask_binary(self):
    
        '''-----\n
        Este metodo sirve para reclasificar la salida de Fmask a una mascara binaria de 0 y 1'''
    
        path_nor = os.path.join(self.nor, self.escena)
        outFile = os.path.join(path_nor, self.escena + '_fmask_binary.img')

        for i in os.listdir(path_nor):
            if i.endswith('CM.img'):
                cloud = os.path.join(path_nor, i)

        with rasterio.drivers():
            with rasterio.open(cloud) as src:
                rs = src.read()
                clouds =  (rs == 2) | (rs == 4) #Aqui elegimos los pixeles con valor 2 (sombra de nubes) o 4 (nubes)
                sind = (rs!=2) & (rs!=4) #Todos los demas pixeles/valores

                rs[clouds] = 1
                rs[sind] = 0

                profile = src.meta
                profile.update(dtype=rasterio.uint8)

                with rasterio.open(outFile, 'w', **profile) as dst:
                    dst.write(rs.astype(rasterio.uint8))
        
    
    
    def clouds(self):
        
        self.fmask()
        self.mascara_cloud_pn()
        self.get_cloud_pn()
        
        
    def m_import(self):
        
        self.createG_bat()
        self.callG_bat()
              
        
    def kl(self):
        
        ini = time.time()
        self.mascara_kl()
        self.make_hist()
        self.get_kl()
                
    def importacion(self):
        
        ini = time.time()
        
        self.clouds()
        self.m_import()
        self.kl()
        self.remove_masks()
        
        print "Mascara de nubes, importacion y obtencion de kls concluido en  " + str(time.time() - ini) + " segundos"
        
    def reproyeccion(self):
        
        ini = time.time()
        
        self.reproject()
        self.copyDocG()
        self.modifyDocG()
        self.modifyRelG()
        
        #Insertamos los datos en la MongoDB
        connection = pymongo.MongoClient("mongodb://localhost")
        db=connection.teledeteccion
        landsat = db.landsat
        
        try:
        
            landsat.update_one({'_id':self.escena}, {'$set':{'Info.Pasos.geo':{'Georef':'True', 'Fecha': time.ctime()}}})
            
        except Exception as e:
            print "Unexpected error:", type(e), e
            
        print "Reproyeccion realizada en  " + str(time.time() - ini) + " segundos"
        
    def Corrad(self):
        
        ini = time.time()
        
        self.copy_files_GR()
        self.createR_bat()
        self.callR_bat()
        self.cleanR()
        self.modify_hdr_rad()
        self.correct_sup_inf()
        self.clean_correct_R()
        self.modify_hdr_rad_255()
        self.translate_bytes_gdal() 
        self.modifyRelRad()
        self.re_clean_R()
        self.modifyDocR()
        
        #Sacamos los valores del kl. 
        path_rad_escena = os.path.join(self.rad, self.escena)
        for i in os.listdir(path_rad_escena):
            if i.endswith('.rad'):
                rad = os.path.join(path_rad_escena, i)
                f = open(rad, 'r')
                lista = []
                for l in f:
                    try:
                        lista.append(int(l[-5:-1]))
                    except:
                        continue
                f.close()
        bandas = ['b1', 'b2', 'b3', 'b4', 'b5', 'b6', 'b7', 'b9']
        kl_values = dict(zip(bandas, lista))
        
        #Insertamos los datos en MongoDB
        connection = pymongo.MongoClient("mongodb://localhost")
        db=connection.teledeteccion
        landsat = db.landsat
        
        try:
        
            landsat.update_one({'_id':self.escena}, {'$set':{'Info.Pasos.rad': {'Corrad': 'True', 'Kl-Values': kl_values, 'Fecha': time.ctime()}}})
            
        except Exception as e:
            print "Unexpected error:", type(e), e
            
        print "Correccion radiometrica realizada en  " + str(time.time() - ini) + " segundos"
        
    
    def normalizacion(self):
        
        ini = time.time()
        
        self.normalize()
        self.copyDocR()
        self.modifyRelNor()
        self.fmask_binary()
        
        #Insertamos los datos en MongoDB
        connection = pymongo.MongoClient("mongodb://localhost")
        db=connection.teledeteccion
        landsat = db.landsat
        
        try:
        
            landsat.update_one({'_id':self.escena}, {'$set':{'Info.Finalizada': time.ctime()}})
            
        except Exception as e:
            print "Unexpected error:", type(e), e
                    
        print "Normalizacion realizada en  " + str(time.time() - ini) + " segundos"
        #No hemos insertado los datos en MongoDB en este caso porque se ha hecho directamente desde normalize
        
        
    def run_all(self): 
        
        #Lo mas comodo, desde aqui se llaman a todos los pasos. Se llama este metodo y en un cafe esta acabado
                
        ini = time.time()
        
        self.importacion()
        self.reproyeccion()
        self.Corrad()
        self.normalizacion()                       
                
        
        print "Escena finalizada en  " + str((time.time() - ini)/60) + " minutos"

### ToDo: Incluir download,  upload to venus 