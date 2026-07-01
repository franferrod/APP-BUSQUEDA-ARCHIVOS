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

                Dictionary<string, string> props = new Dictionary<string, string>();
                
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

                // Get configuration properties
                SwDMConfigurationMgr cfgMgr = doc.ConfigurationManager;
                if (cfgMgr != null)
                {
                    string[] cfgNames = (string[])cfgMgr.GetConfigurationNames();
                    if (cfgNames != null && cfgNames.Length > 0)
                    {
                        SwDMConfiguration cfg = cfgMgr.GetConfigurationByName(cfgNames[0]);
                        if (cfg != null)
                        {
                            string[] cfgPropNames = (string[])cfg.GetCustomPropertyNames();
                            if (cfgPropNames != null)
                            {
                                ISwDMConfiguration14 cfg14 = cfg as ISwDMConfiguration14;
                                foreach (string name in cfgPropNames)
                                {
                                    // Configuration properties override document properties
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
                                    
                                    if (val != null && !string.IsNullOrEmpty(val)) {
                                        props[name] = val;
                                    }
                                }
                            }
                        }
                    }
                }

                doc.CloseDoc();

                JavaScriptSerializer serializer = new JavaScriptSerializer();
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
