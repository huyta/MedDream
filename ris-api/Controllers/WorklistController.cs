using System.Globalization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using RisApi.Data;
using RisApi.Models;

namespace RisApi.Controllers;

/// <summary>
/// DICOM Modality Worklist (MWL) Controller.
/// Serves live scheduled examination datasets to Orthanc PACS or modality SCUs
/// formatted with explicit DICOM Hexadecimal Tag keys matching DICOM PS 3.4 Annex K.
/// </summary>
[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public class WorklistController : ControllerBase
{
    private readonly RisDbContext _dbContext;
    private readonly ILogger<WorklistController> _logger;

    public WorklistController(RisDbContext dbContext, ILogger<WorklistController> logger)
    {
        _dbContext = dbContext ?? throw new ArgumentNullException(nameof(dbContext));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <summary>
    /// Fetches scheduled exams filtered by modality and scheduled date.
    /// Returns a JSON array formatted with explicit DICOM hexadecimal tag keys.
    /// </summary>
    /// <param name="modality">Optional modality code filter (e.g., CT, MR, US, DX, CR).</param>
    /// <param name="date">Optional date filter in DICOM DA format (YYYYMMDD). Defaults to today's date if omitted.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>HTTP 200 with an array of DICOM-tagged worklist items.</returns>
    [HttpGet]
    public async Task<IActionResult> GetWorklist(
        [FromQuery] string? modality = null,
        [FromQuery] string? date = null,
        CancellationToken cancellationToken = default)
    {
        _logger.LogInformation("Incoming MWL query: Modality='{Modality}', Date='{Date}'", modality, date);

        // 1. Resolve Target Scheduled Date (DICOM DA Format: YYYYMMDD)
        DateTime targetDate;
        if (!string.IsNullOrWhiteSpace(date))
        {
            // DICOM standard date format YYYYMMDD (or handle date ranges like YYYYMMDD-YYYYMMDD)
            var cleanDate = date.Trim();
            if (cleanDate.Contains('-'))
            {
                cleanDate = cleanDate.Split('-')[0].Trim();
            }

            if (!DateTime.TryParseExact(cleanDate, "yyyyMMdd", CultureInfo.InvariantCulture, DateTimeStyles.None, out targetDate))
            {
                _logger.LogWarning("Invalid date parameter received: '{Date}'. Expected YYYYMMDD.", date);
                return BadRequest(new { error = $"Invalid date format '{date}'. Expected YYYYMMDD." });
            }
        }
        else
        {
            // Default to today (UTC)
            targetDate = DateTime.UtcNow.Date;
        }

        // Establish range boundaries for SARGable indexing on PostgreSQL
        var startOfDay = DateTime.SpecifyKind(targetDate.Date, DateTimeKind.Utc);
        var endOfDay = startOfDay.AddDays(1);

        try
        {
            // 2. Query Scheduled Exams from PostgreSQL via EF Core
            var query = _dbContext.Exams
                .AsNoTracking()
                .Include(e => e.Patient)
                .Where(e => e.ScheduledDateTime >= startOfDay && e.ScheduledDateTime < endOfDay)
                .Where(e => e.Status == ExamStatus.Scheduled || e.Status == ExamStatus.Waiting);

            // Apply optional Modality filter (case-insensitive)
            if (!string.IsNullOrWhiteSpace(modality))
            {
                var cleanModality = modality.Trim().ToUpperInvariant();
                query = query.Where(e => e.Modality.ToUpper() == cleanModality);
            }

            var exams = await query
                .OrderBy(e => e.ScheduledDateTime)
                .ToListAsync(cancellationToken);

            _logger.LogInformation("Found {Count} scheduled exam(s) matching criteria.", exams.Count);

            // 3. Map to Explicit DICOM Hexadecimal Tag Dictionaries
            var worklistResponses = exams.Select(exam =>
            {
                var patient = exam.Patient;

                // Patient Name in DICOM PN format: LastName^FirstName (or fallback to FullName)
                var formattedPatientName = FormatDicomPersonName(patient.LastName, patient.FirstName, patient.FullName);

                // Patient Birth Date in DICOM DA format: YYYYMMDD
                var formattedBirthDate = patient.BirthDate.HasValue
                    ? patient.BirthDate.Value.ToString("yyyyMMdd", CultureInfo.InvariantCulture)
                    : string.Empty;

                // Scheduled Step Date (YYYYMMDD) and Time (HHMMSS)
                var stepDate = exam.ScheduledDateTime.ToString("yyyyMMdd", CultureInfo.InvariantCulture);
                var stepTime = exam.ScheduledDateTime.ToString("HHmmss", CultureInfo.InvariantCulture);

                // Ensure Study Instance UID exists or generate a deterministic/standard UID
                var studyInstanceUid = !string.IsNullOrWhiteSpace(exam.StudyInstanceUid)
                    ? exam.StudyInstanceUid
                    : GenerateStudyInstanceUid(exam.Id);

                // Scheduled Procedure Step Sequence (0040,0100)
                var spsItem = new Dictionary<string, object?>
                {
                    ["0040,0001"] = !string.IsNullOrWhiteSpace(exam.StationAeTitle) ? exam.StationAeTitle : "ORTHANC", // Scheduled Station AE Title
                    ["0040,0002"] = stepDate,                                                                         // Scheduled Procedure Step Start Date
                    ["0040,0003"] = stepTime,                                                                         // Scheduled Procedure Step Start Time
                    ["0008,0060"] = exam.Modality?.ToUpperInvariant() ?? "OT",                                        // Modality
                    ["0040,0007"] = exam.ProcedureDescription ?? "Diagnostic Imaging",                               // Scheduled Procedure Step Description
                    ["0040,0009"] = exam.ScheduledProcedureStepId ?? $"SPS-{exam.AccessionNumber}",                   // Scheduled Procedure Step ID
                    ["0040,0006"] = exam.PerformingPhysician ?? string.Empty                                          // Scheduled Performing Physician's Name
                };

                // Root DICOM Dataset Map
                var dicomDataset = new Dictionary<string, object?>
                {
                    // Patient Demographics & Identification
                    ["0010,0010"] = formattedPatientName,                                                             // Patient's Name (LastName^FirstName)
                    ["0010,0020"] = patient.PatientId ?? patient.Mrn ?? string.Empty,                                // Patient ID / MRN
                    ["0010,0030"] = formattedBirthDate,                                                               // Patient's Birth Date (YYYYMMDD)
                    ["0010,0040"] = FormatDicomSex(patient.Sex ?? patient.Gender),                                   // Patient's Sex (M, F, O)

                    // Requested Procedure & Study Identification
                    ["0008,0050"] = exam.AccessionNumber ?? string.Empty,                                             // Accession Number
                    ["0020,000d"] = studyInstanceUid,                                                                 // Study Instance UID
                    ["0008,0090"] = exam.ReferringPhysician ?? string.Empty,                                          // Referring Physician's Name
                    ["0032,1060"] = exam.ProcedureDescription ?? string.Empty,                                       // Requested Procedure Description
                    ["0040,1001"] = exam.RequestedProcedureId ?? $"RP-{exam.AccessionNumber}",                       // Requested Procedure ID

                    // Character Set & SOP Class UID
                    ["0008,0005"] = "ISO_IR 100",                                                                     // Specific Character Set (Latin-1)
                    ["0008,0016"] = "1.2.840.10008.5.1.4.31",                                                         // SOP Class UID (Modality Worklist FIND)

                    // Scheduled Procedure Step Sequence (0040,0100) - Nested Array
                    ["0040,0100"] = new List<Dictionary<string, object?>> { spsItem }
                };

                return dicomDataset;
            }).ToList();

            return Ok(worklistResponses);
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Failed to retrieve modality worklist entries from database.");
            return StatusCode(500, new { error = "An internal server error occurred while retrieving worklist items." });
        }
    }

    /// <summary>
    /// Formats person name into DICOM Person Name (PN) format: LastName^FirstName.
    /// </summary>
    private static string FormatDicomPersonName(string? lastName, string? firstName, string? fullName)
    {
        if (!string.IsNullOrWhiteSpace(lastName) || !string.IsNullOrWhiteSpace(firstName))
        {
            return $"{(lastName ?? "").Trim()}^{(firstName ?? "").Trim()}".Trim('^');
        }

        if (!string.IsNullOrWhiteSpace(fullName))
        {
            var parts = fullName.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length == 1) return parts[0];
            // Format as Last^First
            return $"{parts[^1]}^{string.Join(" ", parts.Take(parts.Length - 1))}";
        }

        return "UNKNOWN^PATIENT";
    }

    /// <summary>
    /// Formats sex to standard DICOM CS value: M, F, or O.
    /// </summary>
    private static string FormatDicomSex(string? sex)
    {
        if (string.IsNullOrWhiteSpace(sex)) return "O";
        var s = sex.Trim().ToUpperInvariant();
        if (s.StartsWith("M")) return "M";
        if (s.StartsWith("F")) return "F";
        return "O";
    }

    /// <summary>
    /// Generates a standard DICOM UID if none exists.
    /// </summary>
    private static string GenerateStudyInstanceUid(Guid examId)
    {
        // 2.25 prefix followed by positive decimal integer representation of UUID
        var bytes = examId.ToByteArray();
        var bigInt = new System.Numerics.BigInteger(bytes, isUnsigned: true, isBigEndian: true);
        return $"2.25.{bigInt}";
    }
}
