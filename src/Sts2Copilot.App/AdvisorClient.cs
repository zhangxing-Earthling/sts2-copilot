using System.Net.Http;
using System.Text;
using System.Text.Json;

namespace Sts2Copilot;

/// <summary>
/// Optional local Python rule service. Falls back to the in-process advisor when unavailable.
/// </summary>
public sealed class AdvisorClient : IDisposable
{
    private readonly HttpClient _http;

    public AdvisorClient()
    {
        string url = Environment.GetEnvironmentVariable("STS2_COPILOT_RULES_URL")
                     ?? "http://127.0.0.1:8765";
        _http = new HttpClient
        {
            BaseAddress = new Uri(url),
            Timeout = TimeSpan.FromMilliseconds(500)
        };
    }

    public SolverSnapshot? LastSolver { get; private set; }

    public async Task<List<Advice>?> GetAdviceAsync(GameState state)
    {
        LastSolver = null;
        try
        {
            string json = JsonSerializer.Serialize(state);
            using var content = new StringContent(json, Encoding.UTF8, "application/json");
            using HttpResponseMessage response = await _http.PostAsync("/advise", content);
            if (!response.IsSuccessStatusCode)
            {
                return null;
            }

            string body = await response.Content.ReadAsStringAsync();
            Response? dto = JsonSerializer.Deserialize<Response>(body, new JsonSerializerOptions
            {
                PropertyNameCaseInsensitive = true
            });

            if (dto?.Advice == null || dto.Advice.Count == 0)
            {
                return null;
            }

            LastSolver = dto.Solver;
            return dto.Advice
                .Select(a => new Advice(
                    string.IsNullOrEmpty(a.RuleId) ? "python" : a.RuleId,
                    a.Text ?? "",
                    string.IsNullOrEmpty(a.Severity) ? "info" : a.Severity))
                .ToList();
        }
        catch
        {
            return null;
        }
    }

    public void Dispose()
    {
        _http.Dispose();
    }

    private sealed class Response
    {
        public List<Item>? Advice { get; set; }
        public SolverSnapshot? Solver { get; set; }
    }

    private sealed class Item
    {
        public string? RuleId { get; set; }
        public string? Text { get; set; }
        public string? Severity { get; set; }
    }
}
