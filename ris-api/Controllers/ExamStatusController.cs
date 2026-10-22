using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using RisApi.Data;
using RisApi.Models;

namespace RisApi.Controllers;

/// <summary>
/// Webhook payload received from Orthanc PACS when a study/instance is stored.
/// </summary>
public class CompleteExamRequestDto
{
    [JsonPropertyName("accessionNumber")]
    public string? AccessionNumber { get; set; }

    [JsonPropertyName("studyInstanceUid")]
    public string? StudyInstanceUid { get; set; }

    [JsonPropertyName("stationAeTitle")]
    public string? StationAeTitle { get; set; }

    [JsonPropertyName("modality")]
    public string? Modality { get; set; }

    [JsonPropertyName("instanceCount")]
    public int? InstanceCount { get; set; }
}

/// <summary>
/// Exam Status Controller.
/// Handles automated DICOM storage completion webhooks from Orthanc PACS,
/// transitioning scheduled examinations to 'Completed' in PostgreSQL.
/// </summary>
[ApiController]
[Route("api/exams")]
[Produces("application/json")]
public class ExamStatusController : ControllerBase
{
    private readonly RisDbContext _dbContext;
    private readonly ILogger<ExamStatusController> _logger;

    public ExamStatusController(RisDbContext dbContext, ILogger<ExamStatusController> logger)
    {
        _dbContext = dbContext ?? throw new ArgumentNullException(nameof(dbContext));
        _logger = logger ?? throw new ArgumentNullException(nameof(logger));
    }

    /// <summary>
    /// Marks an examination as Completed when Orthanc finishes storing its DICOM instances.
    /// Idempotent and thread-safe against concurrent triggers.
    /// </summary>
    /// <param name="dto">Payload containing Accession Number and/or Study Instance UID.</param>
    /// <param name="cancellationToken">Cancellation token.</param>
    /// <returns>HTTP 200 with updated status details.</returns>
    [HttpPost("complete")]
    public async Task<IActionResult> MarkExamCompleted(
        [FromBody] CompleteExamRequestDto dto,
        CancellationToken cancellationToken = default)
    {
        if (dto == null || (string.IsNullOrWhiteSpace(dto.AccessionNumber) && string.IsNullOrWhiteSpace(dto.StudyInstanceUid)))
        {
            _logger.LogWarning("Invalid webhook payload: Missing both AccessionNumber and StudyInstanceUid.");
            return BadRequest(new
            {
                error = "Either 'accessionNumber' or 'studyInstanceUid' must be provided in the request payload."
            });
        }

        var accession = dto.AccessionNumber?.Trim();
        var studyUid = dto.StudyInstanceUid?.Trim();

        _logger.LogInformation(
            "Processing exam completion webhook: AccessionNumber='{Accession}', StudyInstanceUid='{StudyUid}', Modality='{Modality}', Slices={Count}",
            accession, studyUid, dto.Modality, dto.InstanceCount);

        try
        {
            // 1. Locate the Exam in PostgreSQL
            Exam? exam = null;

            if (!string.IsNullOrWhiteSpace(accession))
            {
                var cleanAccession = accession.ToUpperInvariant();
                exam = await _dbContext.Exams
                    .Include(e => e.Patient)
                    .FirstOrDefaultAsync(e => e.AccessionNumber.ToUpper() == cleanAccession, cancellationToken);
            }

            if (exam == null && !string.IsNullOrWhiteSpace(studyUid))
            {
                exam = await _dbContext.Exams
                    .Include(e => e.Patient)
                    .FirstOrDefaultAsync(e => e.StudyInstanceUid == studyUid, cancellationToken);
            }

            if (exam == null)
            {
                _logger.LogWarning(
                    "No exam record found in RIS database for Accession='{Accession}' or StudyInstanceUid='{StudyUid}'.",
                    accession, studyUid);

                return NotFound(new
                {
                    error = "Exam not found in RIS database.",
                    accessionNumber = accession,
                    studyInstanceUid = studyUid
                });
            }

            // 2. Idempotency Check: Already Completed
            if (exam.Status == ExamStatus.Completed)
            {
                _logger.LogInformation(
                    "Exam Accession='{Accession}' is already marked as Completed at {CompletedAt}. Returning idempotent 200 OK.",
                    exam.AccessionNumber, exam.CompletionDateTime);

                return Ok(new
                {
                    message = "Exam was already marked as Completed.",
                    examId = exam.Id,
                    accessionNumber = exam.AccessionNumber,
                    studyInstanceUid = exam.StudyInstanceUid ?? studyUid,
                    status = "Completed",
                    completedDateTime = exam.CompletionDateTime
                });
            }

            // 3. Update Status and Timestamp
            var previousStatus = exam.Status.ToString();
            exam.Status = ExamStatus.Completed;
            exam.CompletionDateTime = DateTime.UtcNow;

            // Link StudyInstanceUID if it was not populated during scheduling
            if (string.IsNullOrWhiteSpace(exam.StudyInstanceUid) && !string.IsNullOrWhiteSpace(studyUid))
            {
                exam.StudyInstanceUid = studyUid;
            }

            // Record performing station if provided
            if (!string.IsNullOrWhiteSpace(dto.StationAeTitle) && string.IsNullOrWhiteSpace(exam.StationAeTitle))
            {
                exam.StationAeTitle = dto.StationAeTitle;
            }

            await _dbContext.SaveChangesAsync(cancellationToken);

            _logger.LogInformation(
                "Successfully transitioned Exam Accession='{Accession}' from '{OldStatus}' to 'Completed' at {CompletedAt}.",
                exam.AccessionNumber, previousStatus, exam.CompletionDateTime);

            return Ok(new
            {
                message = "Exam status successfully updated to Completed.",
                examId = exam.Id,
                accessionNumber = exam.AccessionNumber,
                studyInstanceUid = exam.StudyInstanceUid,
                modality = exam.Modality,
                previousStatus = previousStatus,
                status = "Completed",
                completionDateTime = exam.CompletionDateTime,
                patientId = exam.Patient?.PatientId ?? exam.Patient?.Mrn
            });
        }
        catch (DbUpdateConcurrencyException ex)
        {
            _logger.LogWarning(ex, "Concurrency conflict occurred for Accession='{Accession}'. Verifying current state.", accession);

            // Re-fetch to ensure the record ended up completed
            var currentExam = await _dbContext.Exams.AsNoTracking()
                .FirstOrDefaultAsync(e => e.AccessionNumber.ToUpper() == (accession ?? "").ToUpperInvariant(), cancellationToken);

            if (currentExam != null && currentExam.Status == ExamStatus.Completed)
            {
                return Ok(new
                {
                    message = "Exam is completed (concurrency resolved).",
                    accessionNumber = currentExam.AccessionNumber,
                    status = "Completed"
                });
            }

            return StatusCode(500, new { error = "A concurrency conflict occurred while updating exam status." });
        }
        catch (Exception ex)
        {
            _logger.LogError(ex, "Unexpected error completing exam for Accession='{Accession}'.", accession);
            return StatusCode(500, new { error = "An internal error occurred while processing exam completion." });
        }
    }
}
