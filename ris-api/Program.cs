using Microsoft.EntityFrameworkCore;
using RisApi.Data;
using RisApi.Models;

var builder = WebApplication.CreateBuilder(args);

// 1. Configure Services & Database Connection
var connectionString = builder.Configuration.GetConnectionString("DefaultConnection")
    ?? "Host=postgres;Port=5432;Database=ris_db;Username=ris_user;Password=ris_password";

builder.Services.AddDbContext<RisDbContext>(options =>
    options.UseNpgsql(connectionString));

builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen(c =>
{
    c.SwaggerDoc("v1", new() { Title = "RIS Modality Worklist API", Version = "v1" });
});

builder.Services.AddCors(options =>
{
    options.AddDefaultPolicy(policy =>
    {
        policy.AllowAnyOrigin()
              .AllowAnyHeader()
              .AllowAnyMethod();
    });
});

builder.Services.AddHealthChecks();

var app = builder.Build();

// 2. Configure HTTP Pipeline
app.UseCors();

if (app.Environment.IsDevelopment() || true) // Enable Swagger for easy inspection
{
    app.UseSwagger();
    app.UseSwaggerUI(c => c.SwaggerEndpoint("/swagger/v1/swagger.json", "RIS Worklist API v1"));
}

app.UseAuthorization();
app.MapControllers();
app.MapHealthChecks("/health");

// Root information endpoint
app.MapGet("/", () => Results.Ok(new
{
    service = "RIS Modality Worklist API",
    status = "Online",
    worklistEndpoint = "/api/worklist",
    swaggerUi = "/swagger"
}));

// 3. Auto-Migrate Database and Seed Sample Data on Startup
using (var scope = app.Services.CreateScope())
{
    var logger = scope.ServiceProvider.GetRequiredService<ILogger<Program>>();
    var db = scope.ServiceProvider.GetRequiredService<RisDbContext>();

    try
    {
        logger.LogInformation("Ensuring PostgreSQL database and schema are created...");
        await db.Database.EnsureCreatedAsync();

        // Ensure CompletionDateTime column exists if upgrading existing DB
        await db.Database.ExecuteSqlRawAsync(
            "ALTER TABLE \"Exams\" ADD COLUMN IF NOT EXISTS \"CompletionDateTime\" timestamp with time zone;");

        if (!await db.Patients.AnyAsync())
        {
            logger.LogInformation("Seeding initial patients and today's scheduled exams...");

            var today = DateTime.UtcNow.Date;

            // Seed Patient 1
            var patient1 = new Patient
            {
                Id = Guid.NewGuid(),
                PatientId = "PAT-10045",
                Mrn = "MRN-2026-001",
                FirstName = "William",
                LastName = "Davis",
                FullName = "William Davis",
                BirthDate = new DateTime(1982, 4, 15, 0, 0, 0, DateTimeKind.Utc),
                Sex = "M",
                Gender = "Male"
            };

            // Seed Patient 2
            var patient2 = new Patient
            {
                Id = Guid.NewGuid(),
                PatientId = "PAT-10046",
                Mrn = "MRN-2026-002",
                FirstName = "Sophia",
                LastName = "Taylor",
                FullName = "Sophia Taylor",
                BirthDate = new DateTime(1994, 9, 28, 0, 0, 0, DateTimeKind.Utc),
                Sex = "F",
                Gender = "Female"
            };

            // Seed Patient 3
            var patient3 = new Patient
            {
                Id = Guid.NewGuid(),
                PatientId = "PAT-10047",
                Mrn = "MRN-2026-003",
                FirstName = "John",
                LastName = "Doe",
                FullName = "John Doe",
                BirthDate = new DateTime(1975, 11, 10, 0, 0, 0, DateTimeKind.Utc),
                Sex = "M",
                Gender = "Male"
            };

            await db.Patients.AddRangeAsync(patient1, patient2, patient3);

            // Seed Scheduled Exams for Today
            var exam1 = new Exam
            {
                Id = Guid.NewGuid(),
                AccessionNumber = "ACC2026102201",
                Modality = "CT",
                ScheduledDateTime = today.AddHours(9).AddMinutes(30),
                StationAeTitle = "CT_SCANNER_01",
                ProcedureDescription = "CT Chest with IV Contrast",
                RequestedProcedureId = "RP-CT-CHEST",
                ScheduledProcedureStepId = "SPS-CT-001",
                ReferringPhysician = "Miller^Sarah",
                PerformingPhysician = "Taylor^Mark",
                StudyInstanceUid = "2.25.13847291048291048102948192039102",
                Status = ExamStatus.Scheduled,
                PatientId = patient1.Id
            };

            var exam2 = new Exam
            {
                Id = Guid.NewGuid(),
                AccessionNumber = "ACC2026102202",
                Modality = "MR",
                ScheduledDateTime = today.AddHours(11).AddMinutes(0),
                StationAeTitle = "MR_SCANNER_3T",
                ProcedureDescription = "MRI Lumbar Spine Without Contrast",
                RequestedProcedureId = "RP-MR-SPINE",
                ScheduledProcedureStepId = "SPS-MR-002",
                ReferringPhysician = "House^Gregory",
                PerformingPhysician = "Wilson^James",
                StudyInstanceUid = "2.25.29481029481029481029481029481023",
                Status = ExamStatus.Scheduled,
                PatientId = patient2.Id
            };

            var exam3 = new Exam
            {
                Id = Guid.NewGuid(),
                AccessionNumber = "ACC2026102203",
                Modality = "US",
                ScheduledDateTime = today.AddHours(14).AddMinutes(15),
                StationAeTitle = "US_ROOM_2",
                ProcedureDescription = "Ultrasound Whole Abdomen",
                RequestedProcedureId = "RP-US-ABDOMEN",
                ScheduledProcedureStepId = "SPS-US-003",
                ReferringPhysician = "Watson^John",
                PerformingPhysician = "Grey^Meredith",
                StudyInstanceUid = "2.25.38472910482019481029481029481024",
                Status = ExamStatus.Scheduled,
                PatientId = patient3.Id
            };

            await db.Exams.AddRangeAsync(exam1, exam2, exam3);
            await db.SaveChangesAsync();

            logger.LogInformation("Successfully seeded 3 patients and 3 scheduled exams for today.");
        }
        else
        {
            logger.LogInformation("Database already contains records. Skipping seed.");
        }
    }
    catch (Exception ex)
    {
        logger.LogError(ex, "An error occurred during database migration/seeding.");
    }
}

app.Run();
