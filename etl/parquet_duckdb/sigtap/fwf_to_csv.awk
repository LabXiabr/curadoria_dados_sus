BEGIN {
    OFS = ","
    n_w = split(widths, W, "|")
    n_f = split(fields, F, "|")
    if (n_w != n_f) {
        print "layout invalido: widths != fields" > "/dev/stderr"
        exit 10
    }

    for (i = 1; i <= n_f; i++) {
        v = F[i]
        gsub(/"/, "\"\"", v)
        printf "\"%s\"%s", v, (i < n_f ? OFS : ORS)
    }
}
{
    sub(/\r$/, "", $0)
    pos = 1

    for (i = 1; i <= n_w; i++) {
        v = substr($0, pos, W[i])
        pos += W[i]

        # Padding do formato fixo e espaco ASCII; nao alterar TABs ou outros
        # caracteres internos da descricao.
        sub(/^ +/, "", v)
        sub(/ +$/, "", v)

        # RFC 4180: duplica aspas e envolve todo campo em aspas.
        gsub(/"/, "\"\"", v)
        printf "\"%s\"%s", v, (i < n_w ? OFS : ORS)
    }
}
