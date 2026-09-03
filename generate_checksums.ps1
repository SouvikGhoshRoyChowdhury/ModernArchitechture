Get-FileHash `
    "release\Food_Agri_ESG_Builder_1.0.0.zip" `
    -Algorithm SHA256 |
    Format-List |
    Out-File "release\Food_Agri_ESG_Builder_1.0.0_SHA256.txt"

Get-FileHash `
    "release\Transport_Logistics_ESG_Builder_1.0.0.zip" `
    -Algorithm SHA256 |
    Format-List |
    Out-File "release\Transport_Logistics_ESG_Builder_1.0.0_SHA256.txt"

Get-FileHash `
    "release\Public_ESG_Builder_1.0.0.zip" `
    -Algorithm SHA256 |
    Format-List |
    Out-File "release\Public_ESG_Builder_1.0.0_SHA256.txt"