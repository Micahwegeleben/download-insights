Sub ImportCSVAndAnalyze()
    Dim wb          As Workbook
    Dim dataSheet   As Worksheet
    Dim analysisSheet As Worksheet
    Dim FilePath    As String
    Dim i           As Long, j As Long
    Dim DataArray() As Variant
    Dim LastRow     As Long
    Dim Column      As Integer
    Dim TotalDataDownloaded As Double
    Dim FirstDownloadDate As Date, LastDownloadDate As Date, DaysBetween As Long, AverageFilesPerDay As Double
    Dim TotalFilesDownloaded As Long
    Dim DomainCounts As Object
    Dim DomainValue As String
    Dim Key As Variant
    Dim ExtensionCounts As Object
    Dim ExtensionValue As String

    Set wb = ThisWorkbook
    FilePath = wb.Path & "\downloadInsightsAnalytics.csv"
    
    'Create/Replace our 2 sheets
    On Error Resume Next
    Set dataSheet = wb.Sheets("Data")
    If dataSheet Is Nothing Then
        Set dataSheet = wb.Sheets.Add(Before:=wb.Sheets(1))
        dataSheet.Name = "Data"
    Else
        dataSheet.Cells.ClearContents
    End If
    On Error GoTo 0

    On Error Resume Next
    Set analysisSheet = wb.Sheets("Download Analysis")
    If analysisSheet Is Nothing Then
        Set analysisSheet = wb.Sheets.Add(After:=wb.Sheets(wb.Sheets.Count))
        analysisSheet.Name = "Download Analysis"
    Else
        analysisSheet.Cells.ClearContents
    End If
    On Error GoTo 0

    'Transfer CSV to Excel
    Open FilePath For Input As #1
    i = 0
    Do While Not EOF(1)
        i = i + 1
        Line Input #1, LineData
        Fields = Split(LineData, ",")
        For j = 0 To UBound(Fields)
            dataSheet.Cells(i, j + 1).Value = Fields(j)
        Next j
    Loop
    Close #1
    
    'ANALYSIS: Total Data Downloaded
    TotalDataDownloaded = 0
    Column = 5
    LastRow = dataSheet.Cells(Rows.Count, Column).End(xlUp).Row
    For i = 2 To LastRow
        If IsNumeric(dataSheet.Cells(i, Column).Value) Then
            TotalDataDownloaded = TotalDataDownloaded + CDbl(dataSheet.Cells(i, Column).Value)
        End If
    Next i
    
    'ANALYSIS: Total Files Downloaded **
    TotalFilesDownloaded = dataSheet.Cells(Rows.Count, 1).End(xlUp).Row - 1
    
    'ANALYSIS: Average Files Per Day
    Column = 1
    FirstDownloadDate = DateValue(dataSheet.Cells(2, Column).Value)
    LastDownloadDate = Date
    DaysBetween = DateDiff("d", FirstDownloadDate, LastDownloadDate)
    If DaysBetween > 0 Then
        AverageFilesPerDay = TotalFilesDownloaded / DaysBetween
    Else
        AverageFilesPerDay = TotalFilesDownloaded
    End If
    
    'ANALYSIS: Number of Files Downloaded From Each Domain
    Column = 4
    Set DomainCounts = CreateObject("Scripting.Dictionary")
    For i = 2 To dataSheet.Cells(Rows.Count, Column).End(xlUp).Row
        DomainValue = dataSheet.Cells(i, Column).Value
        If DomainCounts.Exists(DomainValue) Then
            DomainCounts(DomainValue) = DomainCounts(DomainValue) + 1
        Else
            DomainCounts.Add DomainValue, 1
        End If
    Next i

    'ANALYSIS: Number of Files Downloaded From Each Extension
    Column = 6
    Set ExtensionCounts = CreateObject("Scripting.Dictionary")
    For i = 2 To dataSheet.Cells(Rows.Count, Column).End(xlUp).Row
        ExtensionValue = dataSheet.Cells(i, Column).Value
        If ExtensionCounts.Exists(ExtensionValue) Then
            ExtensionCounts(ExtensionValue) = ExtensionCounts(ExtensionValue) + 1
        Else
            ExtensionCounts.Add ExtensionValue, 1
        End If
    Next i
    
    'WRITE DATA
    analysisSheet.Cells(1, 1).Value = "Total Data Downloaded (Bytes)"
    analysisSheet.Cells(2, 1).Value = TotalDataDownloaded
    analysisSheet.Cells(1, 2).Value = "Total Files Downloaded"
    analysisSheet.Cells(2, 2).Value = TotalFilesDownloaded
    analysisSheet.Cells(1, 3).Value = "Average Files Per Day"
    analysisSheet.Cells(2, 3).Value = AverageFilesPerDay
    analysisSheet.Cells(1, 5).Value = "Domain"
    analysisSheet.Cells(1, 6).Value = "File Count"
    analysisSheet.Cells(1, 8).Value = "File Extension"
    analysisSheet.Cells(1, 9).Value = "File Count"
    
    'Write how many files were downloaded from each domain
    i = 2
    For Each Key In DomainCounts.Keys
        analysisSheet.Cells(i, 5).Value = Key
        analysisSheet.Cells(i, 6).Value = DomainCounts(Key)
        i = i + 1
    Next Key
    
    'Write how many files were downloaded from each extension
    i = 2
    For Each Key In ExtensionCounts.Keys
        analysisSheet.Cells(i, 8).Value = Key
        analysisSheet.Cells(i, 9).Value = ExtensionCounts(Key)
        i = i + 1
    Next Key
    
    'end
    dataSheet.Columns.AutoFit
    analysisSheet.Columns.AutoFit
    MsgBox "CSV file imported And analyzed!", vbInformation
    
End Sub