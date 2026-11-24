<img width="920" height="777" alt="make1" src="https://github.com/user-attachments/assets/cf6ff6a3-9aa8-4379-b8b7-697112d02919" />
<img width="917" height="563" alt="make2" src="https://github.com/user-attachments/assets/b47ecca6-1bf2-4283-a2da-60bad55331a9" />

Automatización del Pipeline en Make (Google Drive + Apify)<p>
Para automatizar la ejecución del flujo de punta a punta y facilitar la actualización periódica de la información, se diseñó un escenario en Make que conecta Google Drive con Apify: <p>
1.	Descarga de datasets de entrada (Módulos 1 y 2 — Google Drive: Download a File): Se recuperan los archivos en formato CSV desde la carpeta de Google Drive correspondiente (el dataset de delitos y el de alumbrado público). El uso de CSV permite trabajar con archivos ligeros y estandarizados, facilitando que al reemplazar el archivo de delitos por una versión más reciente el flujo siga operando sin fricciones. <p>
2.	Procesamiento ETL y predicción (Módulo 3 — Apify: Run an Actor): Se dispara el Actor de Apify encargado de ejecutar el proceso ETL, integrar los datos espaciales y aplicar el modelo para generar las predicciones correspondientes. <p>
3.	Recuperación de resultados (Módulo 4 — Apify: Get Dataset Items): Una vez finalizada la ejecución del Actor, se extraen los registros procesados y las predicciones generadas desde el dataset de salida de Apify. <p>
4.	Respaldo en Drive en formato CSV (Módulo 5 — Google Drive: Upload a File): El resultado se guarda como archivo CSV en Google Drive, brindando un acceso cómodo y centralizado a los datos generados para consulta o auditoría. <p>
5.	Actualización del dashboard interactivo (Módulo 6 — Apify: Run an Actor): Finalmente, se ejecuta un segundo Actor de Apify que construye/actualiza el dashboard interactivo, logrando que cada corrida del escenario en Make refresque automáticamente los datos visualizados.<p>
Automatización del Pipeline en Make (Google Drive + Apify)<p>
Para automatizar la ejecución del flujo de punta a punta y facilitar la actualización periódica de la información, se diseñó un escenario en Make que conecta Google Drive con Apify: <p>
1.	Descarga de datasets de entrada (Módulos 1 y 2 — Google Drive: Download a File): Se recuperan los archivos en formato CSV desde la carpeta de Google Drive correspondiente (el dataset de delitos y el de alumbrado público). El uso de CSV permite trabajar con archivos ligeros y estandarizados, facilitando que al reemplazar el archivo de delitos por una versión más reciente el flujo siga operando sin fricciones. <p>
2.	Procesamiento ETL y predicción (Módulo 3 — Apify: Run an Actor): Se dispara el Actor de Apify encargado de ejecutar el proceso ETL, integrar los datos espaciales y aplicar el modelo para generar las predicciones correspondientes. <p>
3.	Recuperación de resultados (Módulo 4 — Apify: Get Dataset Items): Una vez finalizada la ejecución del Actor, se extraen los registros procesados y las predicciones generadas desde el dataset de salida de Apify. <p>
4.	Respaldo en Drive en formato CSV (Módulo 5 — Google Drive: Upload a File): El resultado se guarda como archivo CSV en Google Drive, brindando un acceso cómodo y centralizado a los datos generados para consulta o auditoría. <p>
5.	Actualización del dashboard interactivo (Módulo 6 — Apify: Run an Actor): Finalmente, se ejecuta un segundo Actor de Apify que construye/actualiza el dashboard interactivo, logrando que cada corrida del escenario en Make refresque automáticamente los datos visualizados.<p>

<h1>Links a los datasets usados: </h1><p>
https://drive.google.com/file/d/1G0lBDkArGDSzf2mnJt4Aerqcsj4IICCE/view?usp=drive_link<p>
https://drive.google.com/file/d/1GDtIzAXRb5mmS1G-pjJuVHuRPX6YTcCn/view?usp=drive_link<p>
https://drive.google.com/file/d/17cdk4b-NNz4d4SL3di9zwoVC5q4dAIMR/view?usp=drive_link<p>
https://data.buenosaires.gob.ar/dataset/alumbrado-led<p>
https://mapa.seguridadciudad.gob.ar/<p>
