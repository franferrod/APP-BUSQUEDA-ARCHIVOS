using System;
using System.IO;
using SolidWorks.Interop.swdocumentmgr;
using System.Collections.Generic;
using System.Web.Script.Serialization;

namespace SwPropExtractor
{
    class Program
    {
        static void Main(string[] args)
        {
            if (args.Length < 2)
            {
                Console.WriteLine("{\"error\": \"Usage: SwPropExtractor.exe <license_key> <filepath>\"}");
                Environment.Exit(1);
            }

            string licenseKey = args[0];
            string filePath = args[1];

            if (!File.Exists(filePath))
            {
                Console.WriteLine("{\"error\": \"File not found.\"}");
                Environment.Exit(1);
            }

            try
            {
                SwDMClassFactory classFactory = new SwDMClassFactory();
                SwDMApplication app = classFactory.GetApplication(licenseKey);

                if (app == null)
                {
                    Console.WriteLine("{\"error\": \"Failed to connect to Document Manager. Check license key.\"}");
                    Environment.Exit(1);
                }

                SwDmDocumentType docType = SwDmDocumentType.swDmDocumentUnknown;
                string ext = Path.GetExtension(filePath).ToLower();
                if (ext == ".sldprt") docType = SwDmDocumentType.swDmDocumentPart;
                else if (ext == ".sldasm") docType = SwDmDocumentType.swDmDocumentAssembly;
                else if (ext == ".slddrw") docType = SwDmDocumentType.swDmDocumentDrawing;

                if (docType == SwDmDocumentType.swDmDocumentUnknown)
                {
                    Console.WriteLine("{\"error\": \"Unsupported file extension.\"}");
                    Environment.Exit(1);
                }

                SwDmDocumentOpenError err;
                SwDMDocument doc = app.GetDocument(filePath, docType, true, out err);

                if (doc == null)
                {
                    Console.WriteLine("{\"error\": \"Failed to open document. errorCode: " + ((int)err).ToString() + "\", \"errorCode\": " + ((int)err).ToString() + "}");
                    Environment.Exit(0);
                }

                // V2.0.2: Dictionary<string,object> para poder incluir, además de
                // las propiedades (string), la lista de componentes (array).
                Dictionary<string, object> props = new Dictionary<string, object>();

                // V2.0.3: cada sección con su propio try — un fallo en una parte
                // (p.ej. configuraciones en planos, que no existen y dan E_FAIL)
                // no debe impedir extraer el resto (propiedades, preview...).
                try
                {
                string[] propNames = (string[])doc.GetCustomPropertyNames();
                if (propNames != null)
                {
                    // Try to cast to ISwDMDocument13 for GetCustomPropertyValues
                    ISwDMDocument13 doc13 = doc as ISwDMDocument13;
                    
                    foreach (string name in propNames)
                    {
                        string val = null;
                        SwDmCustomInfoType propType;
                        
                        if (doc13 != null)
                        {
                            string linkedTo;
                            val = doc13.GetCustomPropertyValues(name, out propType, out linkedTo);
                            // If evaluated value is empty, try raw
                            if (string.IsNullOrEmpty(val))
                            {
                                val = doc.GetCustomProperty(name, out propType);
                            }
                        }
                        else
                        {
                            val = doc.GetCustomProperty(name, out propType);
                        }
                        
                        if (val != null) {
                            props[name] = val;
                        }
                    }
                }
                }
                catch { }

                // Get configuration properties — V2.0.0: recorrer TODAS las
                // configuraciones (antes solo la primera). Muchos ensamblajes ALSI
                // guardan MONTAJE/SOLDADURA/etc. en una configuración concreta que
                // puede no ser la primera. Una config solo rellena un valor si aún
                // está vacío, para no pisar un valor válido con uno vacío de otra.
                // V2.0.3: los planos no tienen configuraciones (E_FAIL) — se omite.
                try
                {
                if (docType != SwDmDocumentType.swDmDocumentDrawing)
                {
                SwDMConfigurationMgr cfgMgr = doc.ConfigurationManager;
                if (cfgMgr != null)
                {
                    string[] cfgNames = (string[])cfgMgr.GetConfigurationNames();
                    if (cfgNames != null)
                    {
                        foreach (string cfgName in cfgNames)
                        {
                            SwDMConfiguration cfg = cfgMgr.GetConfigurationByName(cfgName);
                            if (cfg == null) continue;
                            string[] cfgPropNames = (string[])cfg.GetCustomPropertyNames();
                            if (cfgPropNames == null) continue;
                            ISwDMConfiguration14 cfg14 = cfg as ISwDMConfiguration14;
                            foreach (string name in cfgPropNames)
                            {
                                string val = null;
                                SwDmCustomInfoType propType;
                                if (cfg14 != null)
                                {
                                    string linkedTo;
                                    val = cfg14.GetCustomPropertyValues(name, out propType, out linkedTo);
                                    if (string.IsNullOrEmpty(val))
                                        val = cfg.GetCustomProperty(name, out propType);
                                }
                                else
                                {
                                    val = cfg.GetCustomProperty(name, out propType);
                                }
                                if (val != null && !string.IsNullOrEmpty(val))
                                {
                                    // Solo rellena si el valor actual está vacío
                                    object actualObj;
                                    string actual = props.TryGetValue(name, out actualObj) ? actualObj as string : null;
                                    if (string.IsNullOrEmpty(actual))
                                        props[name] = val;
                                }
                            }
                        }
                    }
                }
                }
                }
                catch { }

                // V2.0.2: componentes (solo ensamblajes) — rutas completas de las
                // piezas/subensamblajes insertados, para el "¿en qué ensamblajes se usa?"
                if (docType == SwDmDocumentType.swDmDocumentAssembly)
                {
                    try
                    {
                        SwDMSearchOption opt = app.GetSearchOptionObject();
                        object refsObj = doc.GetAllExternalReferences(opt);
                        if (refsObj != null)
                        {
                            string[] refs = (string[])refsObj;
                            var comps = new System.Collections.Generic.List<string>();
                            foreach (string rf in refs)
                                if (!string.IsNullOrEmpty(rf)) comps.Add(rf);
                            if (comps.Count > 0)
                                props["__COMPONENTES__"] = comps.ToArray();
                        }
                    }
                    catch { }
                }

                // V2.0.3: preview PNG embebido (opt-in con --preview). Funciona en
                // equipos SIN SolidWorks; se usa para la caché de miniaturas en BD.
                bool wantPreview = false;
                for (int i = 2; i < args.Length; i++)
                    if (args[i] == "--preview") wantPreview = true;
                if (wantPreview)
                {
                    try
                    {
                        ISwDMDocument11 doc11 = doc as ISwDMDocument11;
                        if (doc11 != null)
                        {
                            SwDmPreviewError perr;
                            object pngObj = doc11.GetPreviewPNGBitmapBytes(out perr);
                            byte[] pngBytes = pngObj as byte[];
                            if (pngBytes != null && pngBytes.Length > 8)
                                props["__PREVIEW_PNG__"] = Convert.ToBase64String(pngBytes);
                        }
                    }
                    catch { }
                }

                doc.CloseDoc();

                JavaScriptSerializer serializer = new JavaScriptSerializer();
                serializer.MaxJsonLength = 32 * 1024 * 1024;  // previews grandes en base64
                string json = serializer.Serialize(props);
                Console.WriteLine(json);
            }
            catch (Exception ex)
            {
                Console.WriteLine("{\"error\": \"Exception: " + ex.Message.Replace("\"", "\\\"") + "\"}");
                Environment.Exit(1);
            }
        }
    }
}
