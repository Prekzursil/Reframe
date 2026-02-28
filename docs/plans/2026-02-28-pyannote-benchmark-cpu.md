Running in Docker worker:
  input:   /home/runner/work/Reframe/Reframe/samples/sample.wav
  backend: pyannote
  extra:   diarize-pyannote

time="2026-02-28T18:26:05Z" level=warning msg="/home/runner/work/Reframe/Reframe/infra/docker-compose.yml: the attribute `version` is obsolete, it will be ignored, please remove it to avoid potential confusion"
 redis Pulling 
 bc1da058f299 Pulling fs layer 
 09a5a0c32a23 Pulling fs layer 
 bd53938b1271 Pulling fs layer 
 9fe3744a2eac Pulling fs layer 
 7ad54b3c4cef Pulling fs layer 
 2a97533d89ca Pulling fs layer 
 4f4fb700ef54 Pulling fs layer 
 1c2c8d1ee428 Pulling fs layer 
 7ad54b3c4cef Waiting 
 2a97533d89ca Waiting 
 4f4fb700ef54 Waiting 
 1c2c8d1ee428 Waiting 
 9fe3744a2eac Waiting 
 09a5a0c32a23 Downloading [======================================>            ]     721B/948B
 bd53938b1271 Downloading [>                                                  ]  2.087kB/173.4kB
 09a5a0c32a23 Downloading [==================================================>]     948B/948B
 09a5a0c32a23 Verifying Checksum 
 09a5a0c32a23 Download complete 
 bd53938b1271 Verifying Checksum 
 bd53938b1271 Download complete 
 bc1da058f299 Downloading [>                                                  ]  37.68kB/3.644MB
 bc1da058f299 Download complete 
 7ad54b3c4cef Downloading [>                                                  ]  126.3kB/12.41MB
 bc1da058f299 Extracting [>                                                  ]  65.54kB/3.644MB
 9fe3744a2eac Downloading [>                                                  ]   10.3kB/1.003MB
 9fe3744a2eac Downloading [==================================================>]  1.003MB/1.003MB
 9fe3744a2eac Verifying Checksum 
 9fe3744a2eac Download complete 
 2a97533d89ca Downloading [==================================================>]     100B/100B
 2a97533d89ca Verifying Checksum 
 2a97533d89ca Download complete 
 bc1da058f299 Extracting [=================================================> ]  3.604MB/3.644MB
 bc1da058f299 Extracting [==================================================>]  3.644MB/3.644MB
 bc1da058f299 Extracting [==================================================>]  3.644MB/3.644MB
 7ad54b3c4cef Downloading [=================================>                 ]  8.425MB/12.41MB
 4f4fb700ef54 Downloading [==================================================>]      32B/32B
 4f4fb700ef54 Verifying Checksum 
 4f4fb700ef54 Download complete 
 bc1da058f299 Pull complete 
 7ad54b3c4cef Verifying Checksum 
 7ad54b3c4cef Download complete 
 09a5a0c32a23 Extracting [==================================================>]     948B/948B
 09a5a0c32a23 Extracting [==================================================>]     948B/948B
 09a5a0c32a23 Pull complete 
 bd53938b1271 Extracting [=========>                                         ]  32.77kB/173.4kB
 1c2c8d1ee428 Downloading [==================================================>]     576B/576B
 1c2c8d1ee428 Download complete 
 bd53938b1271 Extracting [==================================================>]  173.4kB/173.4kB
 bd53938b1271 Extracting [==================================================>]  173.4kB/173.4kB
 bd53938b1271 Pull complete 
 9fe3744a2eac Extracting [=>                                                 ]  32.77kB/1.003MB
 9fe3744a2eac Extracting [==================================================>]  1.003MB/1.003MB
 9fe3744a2eac Extracting [==================================================>]  1.003MB/1.003MB
 9fe3744a2eac Pull complete 
 7ad54b3c4cef Extracting [>                                                  ]  131.1kB/12.41MB
 7ad54b3c4cef Extracting [===========================>                       ]  6.816MB/12.41MB
 7ad54b3c4cef Extracting [==================================================>]  12.41MB/12.41MB
 7ad54b3c4cef Pull complete 
 2a97533d89ca Extracting [==================================================>]     100B/100B
 2a97533d89ca Extracting [==================================================>]     100B/100B
 2a97533d89ca Pull complete 
 4f4fb700ef54 Extracting [==================================================>]      32B/32B
 4f4fb700ef54 Extracting [==================================================>]      32B/32B
 4f4fb700ef54 Pull complete 
 1c2c8d1ee428 Extracting [==================================================>]     576B/576B
 1c2c8d1ee428 Extracting [==================================================>]     576B/576B
 1c2c8d1ee428 Pull complete 
 redis Pulled 
 Network infra_default  Creating
 Network infra_default  Created
 Volume "infra_redis-data"  Creating
 Volume "infra_redis-data"  Created
 Volume "infra_media-data"  Creating
 Volume "infra_media-data"  Created
 Volume "infra_hf-cache"  Creating
 Volume "infra_hf-cache"  Created
 Volume "infra_argos-data"  Creating
 Volume "infra_argos-data"  Created
 Container infra-redis-1  Creating
 Container infra-redis-1  Created
 Container infra-redis-1  Starting
 Container infra-redis-1  Started
#1 [internal] load local bake definitions
#1 reading from stdin 374B done
#1 DONE 0.0s

#2 [internal] load build definition from Dockerfile.worker
#2 transferring dockerfile: 686B done
#2 DONE 0.0s

#3 [auth] library/python:pull token for registry-1.docker.io
#3 DONE 0.0s

#4 [internal] load metadata for docker.io/library/python:3.11-slim
#4 DONE 0.6s

#5 [internal] load .dockerignore
#5 transferring context: 2B done
#5 DONE 0.0s

#6 [internal] load build context
#6 transferring context: 562.02kB 0.0s done
#6 DONE 0.0s

#7 [ 1/10] FROM docker.io/library/python:3.11-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39
#7 resolve docker.io/library/python:3.11-slim@sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39 done
#7 sha256:fa7a862d74b4decf68fb7d3a85147efc14dbcd3779c0abd56c071d27a1ffee04 1.75kB / 1.75kB done
#7 sha256:992921a8b23a7d2fd769908f7646e7cccd583fea96486a99ace92c7399768847 5.48kB / 5.48kB done
#7 sha256:206356c42440674ecbdf1070cf70ce8ef7885ac2e5c56f1ecf800b758f6b0419 0B / 29.78MB 0.1s
#7 sha256:13159fd0b0512a3ecefe5d5e51affb0ef7eb36b371459c75e34f5c090a0870f4 0B / 1.29MB 0.1s
#7 sha256:269d3f7471e27a9c2542916a49849e76630f22709b7e6063730b617d34d44d6f 0B / 14.36MB 0.1s
#7 sha256:c8271b1f627d0068857dce5b53e14a9558603b527e46f1f901722f935b786a39 10.37kB / 10.37kB done
#7 sha256:206356c42440674ecbdf1070cf70ce8ef7885ac2e5c56f1ecf800b758f6b0419 5.24MB / 29.78MB 0.3s
#7 sha256:13159fd0b0512a3ecefe5d5e51affb0ef7eb36b371459c75e34f5c090a0870f4 1.29MB / 1.29MB 0.1s done
#7 sha256:269d3f7471e27a9c2542916a49849e76630f22709b7e6063730b617d34d44d6f 14.36MB / 14.36MB 0.2s done
#7 sha256:28c7e2bc4784ae35d32ed16d30b72e35df3c3f6a0214492f5be2b11e4b5ae2b0 250B / 250B 0.2s done
#7 sha256:206356c42440674ecbdf1070cf70ce8ef7885ac2e5c56f1ecf800b758f6b0419 11.53MB / 29.78MB 0.4s
#7 sha256:206356c42440674ecbdf1070cf70ce8ef7885ac2e5c56f1ecf800b758f6b0419 29.78MB / 29.78MB 0.6s done
#7 extracting sha256:206356c42440674ecbdf1070cf70ce8ef7885ac2e5c56f1ecf800b758f6b0419 0.1s
#7 extracting sha256:206356c42440674ecbdf1070cf70ce8ef7885ac2e5c56f1ecf800b758f6b0419 0.9s done
#7 extracting sha256:13159fd0b0512a3ecefe5d5e51affb0ef7eb36b371459c75e34f5c090a0870f4
#7 extracting sha256:13159fd0b0512a3ecefe5d5e51affb0ef7eb36b371459c75e34f5c090a0870f4 0.1s done
#7 extracting sha256:269d3f7471e27a9c2542916a49849e76630f22709b7e6063730b617d34d44d6f
#7 extracting sha256:269d3f7471e27a9c2542916a49849e76630f22709b7e6063730b617d34d44d6f 0.7s done
#7 extracting sha256:28c7e2bc4784ae35d32ed16d30b72e35df3c3f6a0214492f5be2b11e4b5ae2b0
#7 extracting sha256:28c7e2bc4784ae35d32ed16d30b72e35df3c3f6a0214492f5be2b11e4b5ae2b0 done
#7 DONE 2.6s

#8 [ 2/10] WORKDIR /worker
#8 DONE 0.0s

#9 [ 3/10] RUN apt-get update     && apt-get install -y --no-install-recommends ffmpeg     && rm -rf /var/lib/apt/lists/*
#9 0.186 Hit:1 http://deb.debian.org/debian trixie InRelease
#9 0.187 Get:2 http://deb.debian.org/debian trixie-updates InRelease [47.3 kB]
#9 0.194 Get:3 http://deb.debian.org/debian-security trixie-security InRelease [43.4 kB]
#9 0.207 Get:4 http://deb.debian.org/debian trixie/main amd64 Packages [9670 kB]
#9 0.275 Get:5 http://deb.debian.org/debian trixie-updates/main amd64 Packages [5412 B]
#9 0.275 Get:6 http://deb.debian.org/debian-security trixie-security/main amd64 Packages [113 kB]
#9 0.910 Fetched 9879 kB in 1s (13.0 MB/s)
#9 0.910 Reading package lists...
#9 1.379 Reading package lists...
#9 1.846 Building dependency tree...
#9 1.956 Reading state information...
#9 2.094 The following additional packages will be installed:
#9 2.094   fontconfig fontconfig-config fonts-dejavu-core fonts-dejavu-mono libaom3
#9 2.094   libasound2-data libasound2t64 libass9 libasyncns0 libatomic1 libavc1394-0
#9 2.094   libavcodec61 libavdevice61 libavfilter10 libavformat61 libavutil59 libblas3
#9 2.094   libbluray2 libbrotli1 libbs2b0 libcaca0 libcairo-gobject2 libcairo2
#9 2.094   libcdio-cdda2t64 libcdio-paranoia2t64 libcdio19t64 libchromaprint1 libcjson1
#9 2.094   libcodec2-1.2 libcom-err2 libdatrie1 libdav1d7 libdbus-1-3 libdc1394-25
#9 2.094   libdecor-0-0 libdeflate0 libdrm-amdgpu1 libdrm-common libdrm-intel1 libdrm2
#9 2.094   libdvdnav4 libdvdread8t64 libedit2 libelf1t64 libexpat1 libfftw3-double3
#9 2.094   libflac14 libflite1 libfontconfig1 libfreetype6 libfribidi0 libgbm1
#9 2.094   libgdk-pixbuf-2.0-0 libgdk-pixbuf2.0-common libgfortran5 libgl1
#9 2.094   libgl1-mesa-dri libglib2.0-0t64 libglvnd0 libglx-mesa0 libglx0 libgme0
#9 2.094   libgnutls30t64 libgomp1 libgraphite2-3 libgsm1 libgssapi-krb5-2
#9 2.094   libharfbuzz0b libhwy1t64 libidn2-0 libiec61883-0 libjack-jackd2-0 libjbig0
#9 2.094   libjpeg62-turbo libjxl0.11 libk5crypto3 libkeyutils1 libkrb5-3
#9 2.094   libkrb5support0 liblapack3 liblcms2-2 liblerc4 liblilv-0-0 libllvm19
#9 2.094   libmbedcrypto16 libmp3lame0 libmpg123-0t64 libmysofa1 libnorm1t64 libnuma1
#9 2.094   libogg0 libopenal-data libopenal1 libopenjp2-7 libopenmpt0t64 libopus0
#9 2.094   libp11-kit0 libpango-1.0-0 libpangocairo-1.0-0 libpangoft2-1.0-0
#9 2.094   libpciaccess0 libpgm-5.3-0t64 libpixman-1-0 libplacebo349 libpng16-16t64
#9 2.094   libpocketsphinx3 libpostproc58 libpulse0 librabbitmq4 librav1e0.7
#9 2.094   libraw1394-11 librist4 librsvg2-2 librubberband2 libsamplerate0
#9 2.095   libsdl2-2.0-0 libsensors-config libsensors5 libserd-0-0 libsharpyuv0
#9 2.095   libshine3 libslang2 libsnappy1v5 libsndfile1 libsodium23 libsord-0-0
#9 2.095   libsoxr0 libspeex1 libsphinxbase3t64 libsratom-0-0 libsrt1.5-gnutls libssh-4
#9 2.095   libsvtav1enc2 libswresample5 libswscale8 libtasn1-6 libthai-data libthai0
#9 2.095   libtheoradec1 libtheoraenc1 libtiff6 libtwolame0 libudfread0 libunibreak6
#9 2.095   libunistring5 libusb-1.0-0 libva-drm2 libva-x11-2 libva2 libvdpau1
#9 2.095   libvidstab1.1 libvorbis0a libvorbisenc2 libvorbisfile3 libvpl2 libvpx9
#9 2.095   libvulkan1 libwayland-client0 libwayland-cursor0 libwayland-egl1
#9 2.095   libwayland-server0 libwebp7 libwebpmux3 libx11-6 libx11-data libx11-xcb1
#9 2.095   libx264-164 libx265-215 libxau6 libxcb-dri3-0 libxcb-glx0 libxcb-present0
#9 2.095   libxcb-randr0 libxcb-render0 libxcb-shape0 libxcb-shm0 libxcb-sync1
#9 2.095   libxcb-xfixes0 libxcb1 libxcursor1 libxdmcp6 libxext6 libxfixes3 libxi6
#9 2.095   libxkbcommon0 libxml2 libxrandr2 libxrender1 libxshmfence1 libxss1 libxv1
#9 2.095   libxvidcore4 libxxf86vm1 libz3-4 libzimg2 libzix-0-0 libzmq5 libzvbi-common
#9 2.095   libzvbi0t64 mesa-libgallium ocl-icd-libopencl1 shared-mime-info x11-common
#9 2.095   xkb-data
#9 2.096 Suggested packages:
#9 2.096   ffmpeg-doc alsa-utils libasound2-plugins libcuda1 libnvcuvid1
#9 2.096   libnvidia-encode1 libbluray-bdj libdvdcss2 libfftw3-bin libfftw3-dev
#9 2.096   low-memory-monitor gnutls-bin krb5-doc krb5-user jackd2 liblcms2-utils
#9 2.096   libportaudio2 libsndio7.0 opus-tools pciutils pulseaudio libraw1394-doc
#9 2.096   librsvg2-bin xdg-utils lm-sensors serdi sordi speex opencl-icd
#9 2.096 Recommended packages:
#9 2.096   alsa-ucm-conf alsa-topology-conf libaacs0 dbus default-libdecor-0-plugin-1
#9 2.096   | libdecor-0-plugin-1 libgdk-pixbuf2.0-bin libglib2.0-data xdg-user-dirs
#9 2.096   krb5-locales pocketsphinx-en-us librsvg2-common va-driver-all | va-driver
#9 2.096   vdpau-driver-all | vdpau-driver mesa-vulkan-drivers | vulkan-icd
#9 2.953 The following NEW packages will be installed:
#9 2.953   ffmpeg fontconfig fontconfig-config fonts-dejavu-core fonts-dejavu-mono
#9 2.953   libaom3 libasound2-data libasound2t64 libass9 libasyncns0 libatomic1
#9 2.953   libavc1394-0 libavcodec61 libavdevice61 libavfilter10 libavformat61
#9 2.953   libavutil59 libblas3 libbluray2 libbrotli1 libbs2b0 libcaca0
#9 2.953   libcairo-gobject2 libcairo2 libcdio-cdda2t64 libcdio-paranoia2t64
#9 2.953   libcdio19t64 libchromaprint1 libcjson1 libcodec2-1.2 libcom-err2 libdatrie1
#9 2.953   libdav1d7 libdbus-1-3 libdc1394-25 libdecor-0-0 libdeflate0 libdrm-amdgpu1
#9 2.953   libdrm-common libdrm-intel1 libdrm2 libdvdnav4 libdvdread8t64 libedit2
#9 2.953   libelf1t64 libexpat1 libfftw3-double3 libflac14 libflite1 libfontconfig1
#9 2.953   libfreetype6 libfribidi0 libgbm1 libgdk-pixbuf-2.0-0 libgdk-pixbuf2.0-common
#9 2.953   libgfortran5 libgl1 libgl1-mesa-dri libglib2.0-0t64 libglvnd0 libglx-mesa0
#9 2.953   libglx0 libgme0 libgnutls30t64 libgomp1 libgraphite2-3 libgsm1
#9 2.953   libgssapi-krb5-2 libharfbuzz0b libhwy1t64 libidn2-0 libiec61883-0
#9 2.953   libjack-jackd2-0 libjbig0 libjpeg62-turbo libjxl0.11 libk5crypto3
#9 2.953   libkeyutils1 libkrb5-3 libkrb5support0 liblapack3 liblcms2-2 liblerc4
#9 2.953   liblilv-0-0 libllvm19 libmbedcrypto16 libmp3lame0 libmpg123-0t64 libmysofa1
#9 2.954   libnorm1t64 libnuma1 libogg0 libopenal-data libopenal1 libopenjp2-7
#9 2.954   libopenmpt0t64 libopus0 libp11-kit0 libpango-1.0-0 libpangocairo-1.0-0
#9 2.954   libpangoft2-1.0-0 libpciaccess0 libpgm-5.3-0t64 libpixman-1-0 libplacebo349
#9 2.954   libpng16-16t64 libpocketsphinx3 libpostproc58 libpulse0 librabbitmq4
#9 2.954   librav1e0.7 libraw1394-11 librist4 librsvg2-2 librubberband2 libsamplerate0
#9 2.954   libsdl2-2.0-0 libsensors-config libsensors5 libserd-0-0 libsharpyuv0
#9 2.954   libshine3 libslang2 libsnappy1v5 libsndfile1 libsodium23 libsord-0-0
#9 2.954   libsoxr0 libspeex1 libsphinxbase3t64 libsratom-0-0 libsrt1.5-gnutls libssh-4
#9 2.954   libsvtav1enc2 libswresample5 libswscale8 libtasn1-6 libthai-data libthai0
#9 2.954   libtheoradec1 libtheoraenc1 libtiff6 libtwolame0 libudfread0 libunibreak6
#9 2.954   libunistring5 libusb-1.0-0 libva-drm2 libva-x11-2 libva2 libvdpau1
#9 2.954   libvidstab1.1 libvorbis0a libvorbisenc2 libvorbisfile3 libvpl2 libvpx9
#9 2.954   libvulkan1 libwayland-client0 libwayland-cursor0 libwayland-egl1
#9 2.954   libwayland-server0 libwebp7 libwebpmux3 libx11-6 libx11-data libx11-xcb1
#9 2.954   libx264-164 libx265-215 libxau6 libxcb-dri3-0 libxcb-glx0 libxcb-present0
#9 2.954   libxcb-randr0 libxcb-render0 libxcb-shape0 libxcb-shm0 libxcb-sync1
#9 2.954   libxcb-xfixes0 libxcb1 libxcursor1 libxdmcp6 libxext6 libxfixes3 libxi6
#9 2.954   libxkbcommon0 libxml2 libxrandr2 libxrender1 libxshmfence1 libxss1 libxv1
#9 2.954   libxvidcore4 libxxf86vm1 libz3-4 libzimg2 libzix-0-0 libzmq5 libzvbi-common
#9 2.955   libzvbi0t64 mesa-libgallium ocl-icd-libopencl1 shared-mime-info x11-common
#9 2.955   xkb-data
#9 3.017 0 upgraded, 205 newly installed, 0 to remove and 0 not upgraded.
#9 3.017 Need to get 133 MB of archives.
#9 3.017 After this operation, 466 MB of additional disk space will be used.
#9 3.017 Get:1 http://deb.debian.org/debian trixie/main amd64 libexpat1 amd64 2.7.1-2 [108 kB]
#9 3.034 Get:2 http://deb.debian.org/debian trixie/main amd64 libaom3 amd64 3.12.1-1 [1871 kB]
#9 3.052 Get:3 http://deb.debian.org/debian trixie/main amd64 libdrm-common all 2.4.124-2 [8288 B]
#9 3.052 Get:4 http://deb.debian.org/debian trixie/main amd64 libdrm2 amd64 2.4.124-2 [39.0 kB]
#9 3.053 Get:5 http://deb.debian.org/debian trixie/main amd64 libva2 amd64 2.22.0-3 [79.4 kB]
#9 3.058 Get:6 http://deb.debian.org/debian trixie/main amd64 libva-drm2 amd64 2.22.0-3 [18.3 kB]
#9 3.059 Get:7 http://deb.debian.org/debian trixie/main amd64 libxau6 amd64 1:1.0.11-1 [20.4 kB]
#9 3.059 Get:8 http://deb.debian.org/debian trixie/main amd64 libxdmcp6 amd64 1:1.1.5-1 [27.8 kB]
#9 3.060 Get:9 http://deb.debian.org/debian trixie/main amd64 libxcb1 amd64 1.17.0-2+b1 [144 kB]
#9 3.061 Get:10 http://deb.debian.org/debian trixie/main amd64 libx11-data all 2:1.8.12-1 [343 kB]
#9 3.062 Get:11 http://deb.debian.org/debian trixie/main amd64 libx11-6 amd64 2:1.8.12-1 [815 kB]
#9 3.065 Get:12 http://deb.debian.org/debian trixie/main amd64 libx11-xcb1 amd64 2:1.8.12-1 [247 kB]
#9 3.066 Get:13 http://deb.debian.org/debian trixie/main amd64 libxcb-dri3-0 amd64 1.17.0-2+b1 [107 kB]
#9 3.067 Get:14 http://deb.debian.org/debian trixie/main amd64 libxext6 amd64 2:1.3.4-1+b3 [50.4 kB]
#9 3.073 Get:15 http://deb.debian.org/debian trixie/main amd64 libxfixes3 amd64 1:6.0.0-2+b4 [20.2 kB]
#9 3.073 Get:16 http://deb.debian.org/debian trixie/main amd64 libva-x11-2 amd64 2.22.0-3 [23.1 kB]
#9 3.074 Get:17 http://deb.debian.org/debian trixie/main amd64 libvdpau1 amd64 1.5-3+b1 [27.2 kB]
#9 3.074 Get:18 http://deb.debian.org/debian trixie/main amd64 libvpl2 amd64 1:2.14.0-1+b1 [129 kB]
#9 3.075 Get:19 http://deb.debian.org/debian trixie/main amd64 ocl-icd-libopencl1 amd64 2.3.3-1 [42.9 kB]
#9 3.075 Get:20 http://deb.debian.org/debian trixie/main amd64 libavutil59 amd64 7:7.1.3-0+deb13u1 [417 kB]
#9 3.077 Get:21 http://deb.debian.org/debian trixie/main amd64 libbrotli1 amd64 1.1.0-2+b7 [307 kB]
#9 3.079 Get:22 http://deb.debian.org/debian-security trixie-security/main amd64 libpng16-16t64 amd64 1.6.48-1+deb13u3 [283 kB]
#9 3.079 Get:23 http://deb.debian.org/debian trixie/main amd64 libfreetype6 amd64 2.13.3+dfsg-1 [452 kB]
#9 3.081 Get:24 http://deb.debian.org/debian trixie/main amd64 fonts-dejavu-mono all 2.37-8 [489 kB]
#9 3.083 Get:25 http://deb.debian.org/debian trixie/main amd64 fonts-dejavu-core all 2.37-8 [840 kB]
#9 3.086 Get:26 http://deb.debian.org/debian trixie/main amd64 fontconfig-config amd64 2.15.0-2.3 [318 kB]
#9 3.088 Get:27 http://deb.debian.org/debian trixie/main amd64 libfontconfig1 amd64 2.15.0-2.3 [392 kB]
#9 3.089 Get:28 http://deb.debian.org/debian trixie/main amd64 libpixman-1-0 amd64 0.44.0-3 [248 kB]
#9 3.090 Get:29 http://deb.debian.org/debian trixie/main amd64 libxcb-render0 amd64 1.17.0-2+b1 [115 kB]
#9 3.091 Get:30 http://deb.debian.org/debian trixie/main amd64 libxcb-shm0 amd64 1.17.0-2+b1 [105 kB]
#9 3.092 Get:31 http://deb.debian.org/debian trixie/main amd64 libxrender1 amd64 1:0.9.12-1 [27.9 kB]
#9 3.092 Get:32 http://deb.debian.org/debian trixie/main amd64 libcairo2 amd64 1.18.4-1+b1 [538 kB]
#9 3.095 Get:33 http://deb.debian.org/debian trixie/main amd64 libcodec2-1.2 amd64 1.2.0-3 [8170 kB]
#9 3.123 Get:34 http://deb.debian.org/debian trixie/main amd64 libdav1d7 amd64 1.5.1-1 [559 kB]
#9 3.125 Get:35 http://deb.debian.org/debian trixie/main amd64 libatomic1 amd64 14.2.0-19 [9308 B]
#9 3.126 Get:36 http://deb.debian.org/debian trixie/main amd64 libglib2.0-0t64 amd64 2.84.4-3~deb13u2 [1518 kB]
#9 3.131 Get:37 http://deb.debian.org/debian trixie/main amd64 libgsm1 amd64 1.0.22-1+b2 [29.3 kB]
#9 3.132 Get:38 http://deb.debian.org/debian trixie/main amd64 libhwy1t64 amd64 1.2.0-2+b2 [676 kB]
#9 3.134 Get:39 http://deb.debian.org/debian trixie/main amd64 liblcms2-2 amd64 2.16-2 [160 kB]
#9 3.135 Get:40 http://deb.debian.org/debian trixie/main amd64 libjxl0.11 amd64 0.11.1-4 [1132 kB]
#9 3.139 Get:41 http://deb.debian.org/debian trixie/main amd64 libmp3lame0 amd64 3.100-6+b3 [363 kB]
#9 3.141 Get:42 http://deb.debian.org/debian trixie/main amd64 libopenjp2-7 amd64 2.5.3-2.1~deb13u1 [205 kB]
#9 3.142 Get:43 http://deb.debian.org/debian trixie/main amd64 libopus0 amd64 1.5.2-2 [2852 kB]
#9 3.153 Get:44 http://deb.debian.org/debian trixie/main amd64 librav1e0.7 amd64 0.7.1-9+b2 [946 kB]
#9 3.156 Get:45 http://deb.debian.org/debian trixie/main amd64 libcairo-gobject2 amd64 1.18.4-1+b1 [130 kB]
#9 3.157 Get:46 http://deb.debian.org/debian trixie/main amd64 libgdk-pixbuf2.0-common all 2.42.12+dfsg-4 [311 kB]
#9 3.158 Get:47 http://deb.debian.org/debian trixie/main amd64 libxml2 amd64 2.12.7+dfsg+really2.9.14-2.1+deb13u2 [698 kB]
#9 3.161 Get:48 http://deb.debian.org/debian trixie/main amd64 shared-mime-info amd64 2.4-5+b2 [760 kB]
#9 3.164 Get:49 http://deb.debian.org/debian trixie/main amd64 libjpeg62-turbo amd64 1:2.1.5-4 [168 kB]
#9 3.165 Get:50 http://deb.debian.org/debian trixie/main amd64 libdeflate0 amd64 1.23-2 [47.3 kB]
#9 3.165 Get:51 http://deb.debian.org/debian trixie/main amd64 libjbig0 amd64 2.1-6.1+b2 [32.1 kB]
#9 3.166 Get:52 http://deb.debian.org/debian trixie/main amd64 liblerc4 amd64 4.0.0+ds-5 [183 kB]
#9 3.167 Get:53 http://deb.debian.org/debian trixie/main amd64 libsharpyuv0 amd64 1.5.0-0.1 [116 kB]
#9 3.167 Get:54 http://deb.debian.org/debian trixie/main amd64 libwebp7 amd64 1.5.0-0.1 [318 kB]
#9 3.169 Get:55 http://deb.debian.org/debian trixie/main amd64 libtiff6 amd64 4.7.0-3+deb13u1 [346 kB]
#9 3.170 Get:56 http://deb.debian.org/debian trixie/main amd64 libgdk-pixbuf-2.0-0 amd64 2.42.12+dfsg-4 [141 kB]
#9 3.171 Get:57 http://deb.debian.org/debian trixie/main amd64 fontconfig amd64 2.15.0-2.3 [463 kB]
#9 3.174 Get:58 http://deb.debian.org/debian trixie/main amd64 libfribidi0 amd64 1.0.16-1 [26.5 kB]
#9 3.174 Get:59 http://deb.debian.org/debian trixie/main amd64 libgraphite2-3 amd64 1.3.14-2+b1 [75.4 kB]
#9 3.175 Get:60 http://deb.debian.org/debian trixie/main amd64 libharfbuzz0b amd64 10.2.0-1+b1 [479 kB]
#9 3.177 Get:61 http://deb.debian.org/debian trixie/main amd64 libthai-data all 0.1.29-2 [168 kB]
#9 3.178 Get:62 http://deb.debian.org/debian trixie/main amd64 libdatrie1 amd64 0.2.13-3+b1 [38.1 kB]
#9 3.178 Get:63 http://deb.debian.org/debian trixie/main amd64 libthai0 amd64 0.1.29-2+b1 [49.4 kB]
#9 3.179 Get:64 http://deb.debian.org/debian trixie/main amd64 libpango-1.0-0 amd64 1.56.3-1 [226 kB]
#9 3.180 Get:65 http://deb.debian.org/debian trixie/main amd64 libpangoft2-1.0-0 amd64 1.56.3-1 [55.6 kB]
#9 3.181 Get:66 http://deb.debian.org/debian trixie/main amd64 libpangocairo-1.0-0 amd64 1.56.3-1 [35.7 kB]
#9 3.181 Get:67 http://deb.debian.org/debian trixie/main amd64 librsvg2-2 amd64 2.60.0+dfsg-1 [1789 kB]
#9 3.187 Get:68 http://deb.debian.org/debian trixie/main amd64 libshine3 amd64 3.1.1-2+b2 [23.1 kB]
#9 3.188 Get:69 http://deb.debian.org/debian trixie/main amd64 libsnappy1v5 amd64 1.2.2-1 [29.3 kB]
#9 3.188 Get:70 http://deb.debian.org/debian trixie/main amd64 libspeex1 amd64 1.2.1-3 [56.8 kB]
#9 3.189 Get:71 http://deb.debian.org/debian trixie/main amd64 libsvtav1enc2 amd64 2.3.0+dfsg-1 [2489 kB]
#9 3.198 Get:72 http://deb.debian.org/debian trixie/main amd64 libgomp1 amd64 14.2.0-19 [137 kB]
#9 3.199 Get:73 http://deb.debian.org/debian trixie/main amd64 libsoxr0 amd64 0.1.3-4+b2 [81.0 kB]
#9 3.199 Get:74 http://deb.debian.org/debian trixie/main amd64 libswresample5 amd64 7:7.1.3-0+deb13u1 [101 kB]
#9 3.200 Get:75 http://deb.debian.org/debian trixie/main amd64 libtheoradec1 amd64 1.2.0~alpha1+dfsg-6 [58.4 kB]
#9 3.200 Get:76 http://deb.debian.org/debian trixie/main amd64 libogg0 amd64 1.3.5-3+b2 [23.8 kB]
#9 3.201 Get:77 http://deb.debian.org/debian trixie/main amd64 libtheoraenc1 amd64 1.2.0~alpha1+dfsg-6 [108 kB]
#9 3.201 Get:78 http://deb.debian.org/debian trixie/main amd64 libtwolame0 amd64 0.4.0-2+b2 [51.3 kB]
#9 3.202 Get:79 http://deb.debian.org/debian trixie/main amd64 libvorbis0a amd64 1.3.7-3 [90.0 kB]
#9 3.202 Get:80 http://deb.debian.org/debian trixie/main amd64 libvorbisenc2 amd64 1.3.7-3 [75.4 kB]
#9 3.205 Get:81 http://deb.debian.org/debian-security trixie-security/main amd64 libvpx9 amd64 1.15.0-2.1+deb13u1 [1115 kB]
#9 3.210 Get:82 http://deb.debian.org/debian trixie/main amd64 libwebpmux3 amd64 1.5.0-0.1 [126 kB]
#9 3.211 Get:83 http://deb.debian.org/debian trixie/main amd64 libx264-164 amd64 2:0.164.3108+git31e19f9-2+b1 [558 kB]
#9 3.213 Get:84 http://deb.debian.org/debian trixie/main amd64 libnuma1 amd64 2.0.19-1 [22.2 kB]
#9 3.214 Get:85 http://deb.debian.org/debian trixie/main amd64 libx265-215 amd64 4.1-2 [1237 kB]
#9 3.218 Get:86 http://deb.debian.org/debian trixie/main amd64 libxvidcore4 amd64 2:1.3.7-1+b2 [252 kB]
#9 3.220 Get:87 http://deb.debian.org/debian trixie/main amd64 libzvbi-common all 0.2.44-1 [71.4 kB]
#9 3.220 Get:88 http://deb.debian.org/debian trixie/main amd64 libzvbi0t64 amd64 0.2.44-1 [278 kB]
#9 3.221 Get:89 http://deb.debian.org/debian trixie/main amd64 libavcodec61 amd64 7:7.1.3-0+deb13u1 [5808 kB]
#9 3.242 Get:90 http://deb.debian.org/debian trixie/main amd64 libasound2-data all 1.2.14-1 [21.1 kB]
#9 3.242 Get:91 http://deb.debian.org/debian trixie/main amd64 libasound2t64 amd64 1.2.14-1 [381 kB]
#9 3.244 Get:92 http://deb.debian.org/debian trixie/main amd64 libraw1394-11 amd64 2.1.2-2+b2 [38.8 kB]
#9 3.244 Get:93 http://deb.debian.org/debian trixie/main amd64 libavc1394-0 amd64 0.5.4-5+b2 [18.2 kB]
#9 3.244 Get:94 http://deb.debian.org/debian trixie/main amd64 libunibreak6 amd64 6.1-3 [21.9 kB]
#9 3.245 Get:95 http://deb.debian.org/debian trixie/main amd64 libass9 amd64 1:0.17.3-1+b1 [114 kB]
#9 3.245 Get:96 http://deb.debian.org/debian trixie/main amd64 libudfread0 amd64 1.1.2-1+b2 [17.7 kB]
#9 3.246 Get:97 http://deb.debian.org/debian trixie/main amd64 libbluray2 amd64 1:1.3.4-1+b2 [138 kB]
#9 3.246 Get:98 http://deb.debian.org/debian trixie/main amd64 libchromaprint1 amd64 1.5.1-7 [42.9 kB]
#9 3.248 Get:99 http://deb.debian.org/debian trixie/main amd64 libdvdread8t64 amd64 6.1.3-2 [86.2 kB]
#9 3.252 Get:100 http://deb.debian.org/debian trixie/main amd64 libdvdnav4 amd64 6.1.1-3+b1 [44.5 kB]
#9 3.253 Get:101 http://deb.debian.org/debian trixie/main amd64 libgme0 amd64 0.6.3-7+b2 [131 kB]
#9 3.254 Get:102 http://deb.debian.org/debian trixie/main amd64 libunistring5 amd64 1.3-2 [477 kB]
#9 3.256 Get:103 http://deb.debian.org/debian trixie/main amd64 libidn2-0 amd64 2.3.8-2 [109 kB]
#9 3.257 Get:104 http://deb.debian.org/debian trixie/main amd64 libp11-kit0 amd64 0.25.5-3 [425 kB]
#9 3.259 Get:105 http://deb.debian.org/debian trixie/main amd64 libtasn1-6 amd64 4.20.0-2 [49.9 kB]
#9 3.259 Get:106 http://deb.debian.org/debian-security trixie-security/main amd64 libgnutls30t64 amd64 3.8.9-3+deb13u2 [1468 kB]
#9 3.262 Get:107 http://deb.debian.org/debian trixie/main amd64 libmpg123-0t64 amd64 1.32.10-1 [149 kB]
#9 3.263 Get:108 http://deb.debian.org/debian trixie/main amd64 libvorbisfile3 amd64 1.3.7-3 [20.9 kB]
#9 3.263 Get:109 http://deb.debian.org/debian trixie/main amd64 libopenmpt0t64 amd64 0.7.13-1+b1 [855 kB]
#9 3.267 Get:110 http://deb.debian.org/debian trixie/main amd64 librabbitmq4 amd64 0.15.0-1 [41.8 kB]
#9 3.267 Get:111 http://deb.debian.org/debian trixie/main amd64 libcjson1 amd64 1.7.18-3.1+deb13u1 [29.8 kB]
#9 3.267 Get:112 http://deb.debian.org/debian trixie/main amd64 libmbedcrypto16 amd64 3.6.5-0.1~deb13u1 [361 kB]
#9 3.269 Get:113 http://deb.debian.org/debian trixie/main amd64 librist4 amd64 0.2.11+dfsg-1 [72.1 kB]
#9 3.269 Get:114 http://deb.debian.org/debian trixie/main amd64 libsrt1.5-gnutls amd64 1.5.4-1 [345 kB]
#9 3.271 Get:115 http://deb.debian.org/debian trixie/main amd64 libkrb5support0 amd64 1.21.3-5 [33.0 kB]
#9 3.272 Get:116 http://deb.debian.org/debian trixie/main amd64 libcom-err2 amd64 1.47.2-3+b7 [25.0 kB]
#9 3.273 Get:117 http://deb.debian.org/debian trixie/main amd64 libk5crypto3 amd64 1.21.3-5 [81.5 kB]
#9 3.273 Get:118 http://deb.debian.org/debian trixie/main amd64 libkeyutils1 amd64 1.6.3-6 [9456 B]
#9 3.277 Get:119 http://deb.debian.org/debian trixie/main amd64 libkrb5-3 amd64 1.21.3-5 [326 kB]
#9 3.279 Get:120 http://deb.debian.org/debian trixie/main amd64 libgssapi-krb5-2 amd64 1.21.3-5 [138 kB]
#9 3.280 Get:121 http://deb.debian.org/debian trixie/main amd64 libssh-4 amd64 0.11.2-1+deb13u1 [209 kB]
#9 3.281 Get:122 http://deb.debian.org/debian trixie/main amd64 libnorm1t64 amd64 1.5.9+dfsg-3.1+b2 [221 kB]
#9 3.282 Get:123 http://deb.debian.org/debian trixie/main amd64 libpgm-5.3-0t64 amd64 5.3.128~dfsg-2.1+b1 [162 kB]
#9 3.282 Get:124 http://deb.debian.org/debian-security trixie-security/main amd64 libsodium23 amd64 1.0.18-1+deb13u1 [165 kB]
#9 3.283 Get:125 http://deb.debian.org/debian trixie/main amd64 libzmq5 amd64 4.3.5-1+b3 [283 kB]
#9 3.285 Get:126 http://deb.debian.org/debian trixie/main amd64 libavformat61 amd64 7:7.1.3-0+deb13u1 [1193 kB]
#9 3.289 Get:127 http://deb.debian.org/debian trixie/main amd64 libbs2b0 amd64 3.1.0+dfsg-8+b1 [12.5 kB]
#9 3.289 Get:128 http://deb.debian.org/debian trixie/main amd64 libflite1 amd64 2.2-7 [12.8 MB]
#9 3.332 Get:129 http://deb.debian.org/debian trixie/main amd64 libserd-0-0 amd64 0.32.4-1 [47.0 kB]
#9 3.333 Get:130 http://deb.debian.org/debian trixie/main amd64 libzix-0-0 amd64 0.6.2-1 [23.1 kB]
#9 3.333 Get:131 http://deb.debian.org/debian trixie/main amd64 libsord-0-0 amd64 0.16.18-1 [18.0 kB]
#9 3.333 Get:132 http://deb.debian.org/debian trixie/main amd64 libsratom-0-0 amd64 0.6.18-1 [17.7 kB]
#9 3.334 Get:133 http://deb.debian.org/debian trixie/main amd64 liblilv-0-0 amd64 0.24.26-1 [43.5 kB]
#9 3.334 Get:134 http://deb.debian.org/debian trixie/main amd64 libmysofa1 amd64 1.3.3+dfsg-1 [1158 kB]
#9 3.339 Get:135 http://deb.debian.org/debian trixie/main amd64 libvulkan1 amd64 1.4.309.0-1 [130 kB]
#9 3.339 Get:136 http://deb.debian.org/debian trixie/main amd64 libplacebo349 amd64 7.349.0-3 [2542 kB]
#9 3.348 Get:137 http://deb.debian.org/debian trixie/main amd64 libblas3 amd64 3.12.1-6 [160 kB]
#9 3.349 Get:138 http://deb.debian.org/debian trixie/main amd64 libgfortran5 amd64 14.2.0-19 [836 kB]
#9 3.352 Get:139 http://deb.debian.org/debian trixie/main amd64 liblapack3 amd64 3.12.1-6 [2447 kB]
#9 3.361 Get:140 http://deb.debian.org/debian trixie/main amd64 libasyncns0 amd64 0.8-6+b5 [12.0 kB]
#9 3.361 Get:141 http://deb.debian.org/debian trixie/main amd64 libdbus-1-3 amd64 1.16.2-2 [178 kB]
#9 3.362 Get:142 http://deb.debian.org/debian trixie/main amd64 libflac14 amd64 1.5.0+ds-2 [210 kB]
#9 3.363 Get:143 http://deb.debian.org/debian trixie/main amd64 libsndfile1 amd64 1.2.2-2+b1 [199 kB]
#9 3.364 Get:144 http://deb.debian.org/debian trixie/main amd64 libpulse0 amd64 17.0+dfsg1-2+b1 [276 kB]
#9 3.365 Get:145 http://deb.debian.org/debian trixie/main amd64 libsphinxbase3t64 amd64 0.8+5prealpha+1-21+b1 [121 kB]
#9 3.366 Get:146 http://deb.debian.org/debian trixie/main amd64 libpocketsphinx3 amd64 0.8+5prealpha+1-15+b4 [126 kB]
#9 3.367 Get:147 http://deb.debian.org/debian trixie/main amd64 libpostproc58 amd64 7:7.1.3-0+deb13u1 [88.3 kB]
#9 3.367 Get:148 http://deb.debian.org/debian trixie/main amd64 libfftw3-double3 amd64 3.3.10-2+b1 [781 kB]
#9 3.370 Get:149 http://deb.debian.org/debian trixie/main amd64 libsamplerate0 amd64 0.2.2-4+b2 [950 kB]
#9 3.374 Get:150 http://deb.debian.org/debian trixie/main amd64 librubberband2 amd64 3.3.0+dfsg-2+b3 [142 kB]
#9 3.375 Get:151 http://deb.debian.org/debian trixie/main amd64 libswscale8 amd64 7:7.1.3-0+deb13u1 [233 kB]
#9 3.376 Get:152 http://deb.debian.org/debian trixie/main amd64 libvidstab1.1 amd64 1.1.0-2+b2 [38.9 kB]
#9 3.380 Get:153 http://deb.debian.org/debian trixie/main amd64 libzimg2 amd64 3.0.5+ds1-1+b2 [244 kB]
#9 3.381 Get:154 http://deb.debian.org/debian trixie/main amd64 libavfilter10 amd64 7:7.1.3-0+deb13u1 [4109 kB]
#9 3.396 Get:155 http://deb.debian.org/debian trixie/main amd64 libslang2 amd64 2.3.3-5+b2 [549 kB]
#9 3.398 Get:156 http://deb.debian.org/debian trixie/main amd64 libcaca0 amd64 0.99.beta20-5 [202 kB]
#9 3.399 Get:157 http://deb.debian.org/debian trixie/main amd64 libcdio19t64 amd64 2.2.0-4 [61.3 kB]
#9 3.400 Get:158 http://deb.debian.org/debian trixie/main amd64 libcdio-cdda2t64 amd64 10.2+2.0.2-1+b1 [17.7 kB]
#9 3.400 Get:159 http://deb.debian.org/debian trixie/main amd64 libcdio-paranoia2t64 amd64 10.2+2.0.2-1+b1 [17.4 kB]
#9 3.401 Get:160 http://deb.debian.org/debian trixie/main amd64 libusb-1.0-0 amd64 2:1.0.28-1 [59.6 kB]
#9 3.401 Get:161 http://deb.debian.org/debian trixie/main amd64 libdc1394-25 amd64 2.2.6-5 [111 kB]
#9 3.402 Get:162 http://deb.debian.org/debian trixie/main amd64 libglvnd0 amd64 1.7.0-1+b2 [52.0 kB]
#9 3.409 Get:163 http://deb.debian.org/debian trixie/main amd64 libxcb-glx0 amd64 1.17.0-2+b1 [122 kB]
#9 3.410 Get:164 http://deb.debian.org/debian trixie/main amd64 libxcb-present0 amd64 1.17.0-2+b1 [106 kB]
#9 3.411 Get:165 http://deb.debian.org/debian trixie/main amd64 libxcb-xfixes0 amd64 1.17.0-2+b1 [109 kB]
#9 3.412 Get:166 http://deb.debian.org/debian trixie/main amd64 libxxf86vm1 amd64 1:1.1.4-1+b4 [19.3 kB]
#9 3.412 Get:167 http://deb.debian.org/debian trixie/main amd64 libdrm-amdgpu1 amd64 2.4.124-2 [22.6 kB]
#9 3.413 Get:168 http://deb.debian.org/debian trixie/main amd64 libpciaccess0 amd64 0.17-3+b3 [51.9 kB]
#9 3.413 Get:169 http://deb.debian.org/debian trixie/main amd64 libdrm-intel1 amd64 2.4.124-2 [64.1 kB]
#9 3.413 Get:170 http://deb.debian.org/debian trixie/main amd64 libelf1t64 amd64 0.192-4 [189 kB]
#9 3.414 Get:171 http://deb.debian.org/debian trixie/main amd64 libedit2 amd64 3.1-20250104-1 [93.8 kB]
#9 3.415 Get:172 http://deb.debian.org/debian trixie/main amd64 libz3-4 amd64 4.13.3-1 [8560 kB]
#9 3.445 Get:173 http://deb.debian.org/debian trixie/main amd64 libllvm19 amd64 1:19.1.7-3+b1 [26.0 MB]
#9 3.533 Get:174 http://deb.debian.org/debian trixie/main amd64 libsensors-config all 1:3.6.2-2 [16.2 kB]
#9 3.533 Get:175 http://deb.debian.org/debian trixie/main amd64 libsensors5 amd64 1:3.6.2-2 [37.5 kB]
#9 3.534 Get:176 http://deb.debian.org/debian trixie/main amd64 libxcb-randr0 amd64 1.17.0-2+b1 [117 kB]
#9 3.534 Get:177 http://deb.debian.org/debian trixie/main amd64 libxcb-sync1 amd64 1.17.0-2+b1 [109 kB]
#9 3.535 Get:178 http://deb.debian.org/debian trixie/main amd64 libxshmfence1 amd64 1.3.3-1 [10.9 kB]
#9 3.536 Get:179 http://deb.debian.org/debian trixie/main amd64 mesa-libgallium amd64 25.0.7-2 [9629 kB]
#9 3.568 Get:180 http://deb.debian.org/debian trixie/main amd64 libwayland-server0 amd64 1.23.1-3 [34.4 kB]
#9 3.568 Get:181 http://deb.debian.org/debian trixie/main amd64 libgbm1 amd64 25.0.7-2 [44.4 kB]
#9 3.569 Get:182 http://deb.debian.org/debian trixie/main amd64 libgl1-mesa-dri amd64 25.0.7-2 [46.1 kB]
#9 3.569 Get:183 http://deb.debian.org/debian trixie/main amd64 libglx-mesa0 amd64 25.0.7-2 [143 kB]
#9 3.570 Get:184 http://deb.debian.org/debian trixie/main amd64 libglx0 amd64 1.7.0-1+b2 [34.9 kB]
#9 3.571 Get:185 http://deb.debian.org/debian trixie/main amd64 libgl1 amd64 1.7.0-1+b2 [89.5 kB]
#9 3.571 Get:186 http://deb.debian.org/debian trixie/main amd64 libiec61883-0 amd64 1.2.0-7 [30.6 kB]
#9 3.572 Get:187 http://deb.debian.org/debian trixie/main amd64 libjack-jackd2-0 amd64 1.9.22~dfsg-4 [287 kB]
#9 3.573 Get:188 http://deb.debian.org/debian trixie/main amd64 libopenal-data all 1:1.24.2-1 [168 kB]
#9 3.578 Get:189 http://deb.debian.org/debian trixie/main amd64 libopenal1 amd64 1:1.24.2-1 [637 kB]
#9 3.580 Get:190 http://deb.debian.org/debian trixie/main amd64 libwayland-client0 amd64 1.23.1-3 [26.8 kB]
#9 3.581 Get:191 http://deb.debian.org/debian trixie/main amd64 libdecor-0-0 amd64 0.2.2-2 [15.5 kB]
#9 3.581 Get:192 http://deb.debian.org/debian trixie/main amd64 libwayland-cursor0 amd64 1.23.1-3 [11.9 kB]
#9 3.582 Get:193 http://deb.debian.org/debian trixie/main amd64 libwayland-egl1 amd64 1.23.1-3 [5860 B]
#9 3.582 Get:194 http://deb.debian.org/debian trixie/main amd64 libxcursor1 amd64 1:1.2.3-1 [39.7 kB]
#9 3.582 Get:195 http://deb.debian.org/debian trixie/main amd64 libxi6 amd64 2:1.8.2-1 [78.9 kB]
#9 3.583 Get:196 http://deb.debian.org/debian trixie/main amd64 xkb-data all 2.42-1 [790 kB]
#9 3.586 Get:197 http://deb.debian.org/debian trixie/main amd64 libxkbcommon0 amd64 1.7.0-2 [113 kB]
#9 3.586 Get:198 http://deb.debian.org/debian trixie/main amd64 libxrandr2 amd64 2:1.5.4-1+b3 [36.3 kB]
#9 3.589 Get:199 http://deb.debian.org/debian trixie/main amd64 x11-common all 1:7.7+24+deb13u1 [217 kB]
#9 3.591 Get:200 http://deb.debian.org/debian trixie/main amd64 libxss1 amd64 1:1.2.3-1+b3 [17.0 kB]
#9 3.591 Get:201 http://deb.debian.org/debian trixie/main amd64 libsdl2-2.0-0 amd64 2.32.4+dfsg-1 [669 kB]
#9 3.594 Get:202 http://deb.debian.org/debian trixie/main amd64 libxcb-shape0 amd64 1.17.0-2+b1 [106 kB]
#9 3.595 Get:203 http://deb.debian.org/debian trixie/main amd64 libxv1 amd64 2:1.0.11-1.1+b3 [23.4 kB]
#9 3.596 Get:204 http://deb.debian.org/debian trixie/main amd64 libavdevice61 amd64 7:7.1.3-0+deb13u1 [119 kB]
#9 3.597 Get:205 http://deb.debian.org/debian trixie/main amd64 ffmpeg amd64 7:7.1.3-0+deb13u1 [1995 kB]
#9 3.721 debconf: unable to initialize frontend: Dialog
#9 3.721 debconf: (TERM is not set, so the dialog frontend is not usable.)
#9 3.721 debconf: falling back to frontend: Readline
#9 3.721 debconf: unable to initialize frontend: Readline
#9 3.721 debconf: (Can't locate Term/ReadLine.pm in @INC (you may need to install the Term::ReadLine module) (@INC entries checked: /etc/perl /usr/local/lib/x86_64-linux-gnu/perl/5.40.1 /usr/local/share/perl/5.40.1 /usr/lib/x86_64-linux-gnu/perl5/5.40 /usr/share/perl5 /usr/lib/x86_64-linux-gnu/perl-base /usr/lib/x86_64-linux-gnu/perl/5.40 /usr/share/perl/5.40 /usr/local/lib/site_perl) at /usr/share/perl5/Debconf/FrontEnd/Readline.pm line 8, <STDIN> line 205.)
#9 3.721 debconf: falling back to frontend: Teletype
#9 3.726 debconf: unable to initialize frontend: Teletype
#9 3.726 debconf: (This frontend requires a controlling tty.)
#9 3.726 debconf: falling back to frontend: Noninteractive
#9 6.837 Preconfiguring packages ...
#9 6.890 Fetched 133 MB in 1s (211 MB/s)
#9 6.909 Selecting previously unselected package libexpat1:amd64.
#9 6.909 (Reading database ... (Reading database ... 5%(Reading database ... 10%(Reading database ... 15%(Reading database ... 20%(Reading database ... 25%(Reading database ... 30%(Reading database ... 35%(Reading database ... 40%(Reading database ... 45%(Reading database ... 50%(Reading database ... 55%(Reading database ... 60%(Reading database ... 65%(Reading database ... 70%(Reading database ... 75%(Reading database ... 80%(Reading database ... 85%(Reading database ... 90%(Reading database ... 95%(Reading database ... 100%(Reading database ... 5645 files and directories currently installed.)
#9 6.917 Preparing to unpack .../000-libexpat1_2.7.1-2_amd64.deb ...
#9 6.920 Unpacking libexpat1:amd64 (2.7.1-2) ...
#9 6.942 Selecting previously unselected package libaom3:amd64.
#9 6.943 Preparing to unpack .../001-libaom3_3.12.1-1_amd64.deb ...
#9 6.944 Unpacking libaom3:amd64 (3.12.1-1) ...
#9 7.035 Selecting previously unselected package libdrm-common.
#9 7.036 Preparing to unpack .../002-libdrm-common_2.4.124-2_all.deb ...
#9 7.037 Unpacking libdrm-common (2.4.124-2) ...
#9 7.052 Selecting previously unselected package libdrm2:amd64.
#9 7.053 Preparing to unpack .../003-libdrm2_2.4.124-2_amd64.deb ...
#9 7.054 Unpacking libdrm2:amd64 (2.4.124-2) ...
#9 7.072 Selecting previously unselected package libva2:amd64.
#9 7.072 Preparing to unpack .../004-libva2_2.22.0-3_amd64.deb ...
#9 7.074 Unpacking libva2:amd64 (2.22.0-3) ...
#9 7.092 Selecting previously unselected package libva-drm2:amd64.
#9 7.093 Preparing to unpack .../005-libva-drm2_2.22.0-3_amd64.deb ...
#9 7.094 Unpacking libva-drm2:amd64 (2.22.0-3) ...
#9 7.110 Selecting previously unselected package libxau6:amd64.
#9 7.111 Preparing to unpack .../006-libxau6_1%3a1.0.11-1_amd64.deb ...
#9 7.112 Unpacking libxau6:amd64 (1:1.0.11-1) ...
#9 7.128 Selecting previously unselected package libxdmcp6:amd64.
#9 7.129 Preparing to unpack .../007-libxdmcp6_1%3a1.1.5-1_amd64.deb ...
#9 7.130 Unpacking libxdmcp6:amd64 (1:1.1.5-1) ...
#9 7.157 Selecting previously unselected package libxcb1:amd64.
#9 7.157 Preparing to unpack .../008-libxcb1_1.17.0-2+b1_amd64.deb ...
#9 7.158 Unpacking libxcb1:amd64 (1.17.0-2+b1) ...
#9 7.176 Selecting previously unselected package libx11-data.
#9 7.177 Preparing to unpack .../009-libx11-data_2%3a1.8.12-1_all.deb ...
#9 7.178 Unpacking libx11-data (2:1.8.12-1) ...
#9 7.226 Selecting previously unselected package libx11-6:amd64.
#9 7.227 Preparing to unpack .../010-libx11-6_2%3a1.8.12-1_amd64.deb ...
#9 7.229 Unpacking libx11-6:amd64 (2:1.8.12-1) ...
#9 7.271 Selecting previously unselected package libx11-xcb1:amd64.
#9 7.272 Preparing to unpack .../011-libx11-xcb1_2%3a1.8.12-1_amd64.deb ...
#9 7.274 Unpacking libx11-xcb1:amd64 (2:1.8.12-1) ...
#9 7.293 Selecting previously unselected package libxcb-dri3-0:amd64.
#9 7.294 Preparing to unpack .../012-libxcb-dri3-0_1.17.0-2+b1_amd64.deb ...
#9 7.295 Unpacking libxcb-dri3-0:amd64 (1.17.0-2+b1) ...
#9 7.314 Selecting previously unselected package libxext6:amd64.
#9 7.315 Preparing to unpack .../013-libxext6_2%3a1.3.4-1+b3_amd64.deb ...
#9 7.316 Unpacking libxext6:amd64 (2:1.3.4-1+b3) ...
#9 7.333 Selecting previously unselected package libxfixes3:amd64.
#9 7.334 Preparing to unpack .../014-libxfixes3_1%3a6.0.0-2+b4_amd64.deb ...
#9 7.335 Unpacking libxfixes3:amd64 (1:6.0.0-2+b4) ...
#9 7.351 Selecting previously unselected package libva-x11-2:amd64.
#9 7.352 Preparing to unpack .../015-libva-x11-2_2.22.0-3_amd64.deb ...
#9 7.353 Unpacking libva-x11-2:amd64 (2.22.0-3) ...
#9 7.370 Selecting previously unselected package libvdpau1:amd64.
#9 7.371 Preparing to unpack .../016-libvdpau1_1.5-3+b1_amd64.deb ...
#9 7.372 Unpacking libvdpau1:amd64 (1.5-3+b1) ...
#9 7.389 Selecting previously unselected package libvpl2.
#9 7.390 Preparing to unpack .../017-libvpl2_1%3a2.14.0-1+b1_amd64.deb ...
#9 7.391 Unpacking libvpl2 (1:2.14.0-1+b1) ...
#9 7.412 Selecting previously unselected package ocl-icd-libopencl1:amd64.
#9 7.413 Preparing to unpack .../018-ocl-icd-libopencl1_2.3.3-1_amd64.deb ...
#9 7.414 Unpacking ocl-icd-libopencl1:amd64 (2.3.3-1) ...
#9 7.432 Selecting previously unselected package libavutil59:amd64.
#9 7.434 Preparing to unpack .../019-libavutil59_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 7.435 Unpacking libavutil59:amd64 (7:7.1.3-0+deb13u1) ...
#9 7.468 Selecting previously unselected package libbrotli1:amd64.
#9 7.469 Preparing to unpack .../020-libbrotli1_1.1.0-2+b7_amd64.deb ...
#9 7.470 Unpacking libbrotli1:amd64 (1.1.0-2+b7) ...
#9 7.500 Selecting previously unselected package libpng16-16t64:amd64.
#9 7.501 Preparing to unpack .../021-libpng16-16t64_1.6.48-1+deb13u3_amd64.deb ...
#9 7.502 Unpacking libpng16-16t64:amd64 (1.6.48-1+deb13u3) ...
#9 7.526 Selecting previously unselected package libfreetype6:amd64.
#9 7.527 Preparing to unpack .../022-libfreetype6_2.13.3+dfsg-1_amd64.deb ...
#9 7.528 Unpacking libfreetype6:amd64 (2.13.3+dfsg-1) ...
#9 7.557 Selecting previously unselected package fonts-dejavu-mono.
#9 7.559 Preparing to unpack .../023-fonts-dejavu-mono_2.37-8_all.deb ...
#9 7.560 Unpacking fonts-dejavu-mono (2.37-8) ...
#9 7.593 Selecting previously unselected package fonts-dejavu-core.
#9 7.595 Preparing to unpack .../024-fonts-dejavu-core_2.37-8_all.deb ...
#9 7.611 Unpacking fonts-dejavu-core (2.37-8) ...
#9 7.660 Selecting previously unselected package fontconfig-config.
#9 7.661 Preparing to unpack .../025-fontconfig-config_2.15.0-2.3_amd64.deb ...
#9 7.662 Unpacking fontconfig-config (2.15.0-2.3) ...
#9 7.688 Selecting previously unselected package libfontconfig1:amd64.
#9 7.689 Preparing to unpack .../026-libfontconfig1_2.15.0-2.3_amd64.deb ...
#9 7.690 Unpacking libfontconfig1:amd64 (2.15.0-2.3) ...
#9 7.713 Selecting previously unselected package libpixman-1-0:amd64.
#9 7.714 Preparing to unpack .../027-libpixman-1-0_0.44.0-3_amd64.deb ...
#9 7.715 Unpacking libpixman-1-0:amd64 (0.44.0-3) ...
#9 7.740 Selecting previously unselected package libxcb-render0:amd64.
#9 7.741 Preparing to unpack .../028-libxcb-render0_1.17.0-2+b1_amd64.deb ...
#9 7.742 Unpacking libxcb-render0:amd64 (1.17.0-2+b1) ...
#9 7.761 Selecting previously unselected package libxcb-shm0:amd64.
#9 7.762 Preparing to unpack .../029-libxcb-shm0_1.17.0-2+b1_amd64.deb ...
#9 7.763 Unpacking libxcb-shm0:amd64 (1.17.0-2+b1) ...
#9 7.780 Selecting previously unselected package libxrender1:amd64.
#9 7.781 Preparing to unpack .../030-libxrender1_1%3a0.9.12-1_amd64.deb ...
#9 7.782 Unpacking libxrender1:amd64 (1:0.9.12-1) ...
#9 7.798 Selecting previously unselected package libcairo2:amd64.
#9 7.799 Preparing to unpack .../031-libcairo2_1.18.4-1+b1_amd64.deb ...
#9 7.800 Unpacking libcairo2:amd64 (1.18.4-1+b1) ...
#9 7.836 Selecting previously unselected package libcodec2-1.2:amd64.
#9 7.837 Preparing to unpack .../032-libcodec2-1.2_1.2.0-3_amd64.deb ...
#9 7.838 Unpacking libcodec2-1.2:amd64 (1.2.0-3) ...
#9 8.116 Selecting previously unselected package libdav1d7:amd64.
#9 8.118 Preparing to unpack .../033-libdav1d7_1.5.1-1_amd64.deb ...
#9 8.119 Unpacking libdav1d7:amd64 (1.5.1-1) ...
#9 8.157 Selecting previously unselected package libatomic1:amd64.
#9 8.158 Preparing to unpack .../034-libatomic1_14.2.0-19_amd64.deb ...
#9 8.159 Unpacking libatomic1:amd64 (14.2.0-19) ...
#9 8.175 Selecting previously unselected package libglib2.0-0t64:amd64.
#9 8.176 Preparing to unpack .../035-libglib2.0-0t64_2.84.4-3~deb13u2_amd64.deb ...
#9 8.184 Unpacking libglib2.0-0t64:amd64 (2.84.4-3~deb13u2) ...
#9 8.254 Selecting previously unselected package libgsm1:amd64.
#9 8.255 Preparing to unpack .../036-libgsm1_1.0.22-1+b2_amd64.deb ...
#9 8.256 Unpacking libgsm1:amd64 (1.0.22-1+b2) ...
#9 8.272 Selecting previously unselected package libhwy1t64:amd64.
#9 8.274 Preparing to unpack .../037-libhwy1t64_1.2.0-2+b2_amd64.deb ...
#9 8.275 Unpacking libhwy1t64:amd64 (1.2.0-2+b2) ...
#9 8.322 Selecting previously unselected package liblcms2-2:amd64.
#9 8.324 Preparing to unpack .../038-liblcms2-2_2.16-2_amd64.deb ...
#9 8.325 Unpacking liblcms2-2:amd64 (2.16-2) ...
#9 8.347 Selecting previously unselected package libjxl0.11:amd64.
#9 8.348 Preparing to unpack .../039-libjxl0.11_0.11.1-4_amd64.deb ...
#9 8.349 Unpacking libjxl0.11:amd64 (0.11.1-4) ...
#9 8.409 Selecting previously unselected package libmp3lame0:amd64.
#9 8.410 Preparing to unpack .../040-libmp3lame0_3.100-6+b3_amd64.deb ...
#9 8.411 Unpacking libmp3lame0:amd64 (3.100-6+b3) ...
#9 8.433 Selecting previously unselected package libopenjp2-7:amd64.
#9 8.434 Preparing to unpack .../041-libopenjp2-7_2.5.3-2.1~deb13u1_amd64.deb ...
#9 8.435 Unpacking libopenjp2-7:amd64 (2.5.3-2.1~deb13u1) ...
#9 8.459 Selecting previously unselected package libopus0:amd64.
#9 8.460 Preparing to unpack .../042-libopus0_1.5.2-2_amd64.deb ...
#9 8.461 Unpacking libopus0:amd64 (1.5.2-2) ...
#9 8.571 Selecting previously unselected package librav1e0.7:amd64.
#9 8.572 Preparing to unpack .../043-librav1e0.7_0.7.1-9+b2_amd64.deb ...
#9 8.573 Unpacking librav1e0.7:amd64 (0.7.1-9+b2) ...
#9 8.626 Selecting previously unselected package libcairo-gobject2:amd64.
#9 8.627 Preparing to unpack .../044-libcairo-gobject2_1.18.4-1+b1_amd64.deb ...
#9 8.628 Unpacking libcairo-gobject2:amd64 (1.18.4-1+b1) ...
#9 8.645 Selecting previously unselected package libgdk-pixbuf2.0-common.
#9 8.646 Preparing to unpack .../045-libgdk-pixbuf2.0-common_2.42.12+dfsg-4_all.deb ...
#9 8.647 Unpacking libgdk-pixbuf2.0-common (2.42.12+dfsg-4) ...
#9 8.679 Selecting previously unselected package libxml2:amd64.
#9 8.681 Preparing to unpack .../046-libxml2_2.12.7+dfsg+really2.9.14-2.1+deb13u2_amd64.deb ...
#9 8.682 Unpacking libxml2:amd64 (2.12.7+dfsg+really2.9.14-2.1+deb13u2) ...
#9 8.723 Selecting previously unselected package shared-mime-info.
#9 8.724 Preparing to unpack .../047-shared-mime-info_2.4-5+b2_amd64.deb ...
#9 8.725 Unpacking shared-mime-info (2.4-5+b2) ...
#9 8.773 Selecting previously unselected package libjpeg62-turbo:amd64.
#9 8.775 Preparing to unpack .../048-libjpeg62-turbo_1%3a2.1.5-4_amd64.deb ...
#9 8.775 Unpacking libjpeg62-turbo:amd64 (1:2.1.5-4) ...
#9 8.796 Selecting previously unselected package libdeflate0:amd64.
#9 8.797 Preparing to unpack .../049-libdeflate0_1.23-2_amd64.deb ...
#9 8.798 Unpacking libdeflate0:amd64 (1.23-2) ...
#9 8.814 Selecting previously unselected package libjbig0:amd64.
#9 8.815 Preparing to unpack .../050-libjbig0_2.1-6.1+b2_amd64.deb ...
#9 8.816 Unpacking libjbig0:amd64 (2.1-6.1+b2) ...
#9 8.832 Selecting previously unselected package liblerc4:amd64.
#9 8.833 Preparing to unpack .../051-liblerc4_4.0.0+ds-5_amd64.deb ...
#9 8.834 Unpacking liblerc4:amd64 (4.0.0+ds-5) ...
#9 8.855 Selecting previously unselected package libsharpyuv0:amd64.
#9 8.856 Preparing to unpack .../052-libsharpyuv0_1.5.0-0.1_amd64.deb ...
#9 8.857 Unpacking libsharpyuv0:amd64 (1.5.0-0.1) ...
#9 8.874 Selecting previously unselected package libwebp7:amd64.
#9 8.875 Preparing to unpack .../053-libwebp7_1.5.0-0.1_amd64.deb ...
#9 8.876 Unpacking libwebp7:amd64 (1.5.0-0.1) ...
#9 8.900 Selecting previously unselected package libtiff6:amd64.
#9 8.901 Preparing to unpack .../054-libtiff6_4.7.0-3+deb13u1_amd64.deb ...
#9 8.902 Unpacking libtiff6:amd64 (4.7.0-3+deb13u1) ...
#9 8.926 Selecting previously unselected package libgdk-pixbuf-2.0-0:amd64.
#9 8.927 Preparing to unpack .../055-libgdk-pixbuf-2.0-0_2.42.12+dfsg-4_amd64.deb ...
#9 8.928 Unpacking libgdk-pixbuf-2.0-0:amd64 (2.42.12+dfsg-4) ...
#9 8.950 Selecting previously unselected package fontconfig.
#9 8.951 Preparing to unpack .../056-fontconfig_2.15.0-2.3_amd64.deb ...
#9 8.952 Unpacking fontconfig (2.15.0-2.3) ...
#9 8.972 Selecting previously unselected package libfribidi0:amd64.
#9 8.973 Preparing to unpack .../057-libfribidi0_1.0.16-1_amd64.deb ...
#9 8.974 Unpacking libfribidi0:amd64 (1.0.16-1) ...
#9 8.989 Selecting previously unselected package libgraphite2-3:amd64.
#9 8.990 Preparing to unpack .../058-libgraphite2-3_1.3.14-2+b1_amd64.deb ...
#9 8.991 Unpacking libgraphite2-3:amd64 (1.3.14-2+b1) ...
#9 9.018 Selecting previously unselected package libharfbuzz0b:amd64.
#9 9.019 Preparing to unpack .../059-libharfbuzz0b_10.2.0-1+b1_amd64.deb ...
#9 9.020 Unpacking libharfbuzz0b:amd64 (10.2.0-1+b1) ...
#9 9.052 Selecting previously unselected package libthai-data.
#9 9.053 Preparing to unpack .../060-libthai-data_0.1.29-2_all.deb ...
#9 9.054 Unpacking libthai-data (0.1.29-2) ...
#9 9.077 Selecting previously unselected package libdatrie1:amd64.
#9 9.078 Preparing to unpack .../061-libdatrie1_0.2.13-3+b1_amd64.deb ...
#9 9.079 Unpacking libdatrie1:amd64 (0.2.13-3+b1) ...
#9 9.095 Selecting previously unselected package libthai0:amd64.
#9 9.096 Preparing to unpack .../062-libthai0_0.1.29-2+b1_amd64.deb ...
#9 9.097 Unpacking libthai0:amd64 (0.1.29-2+b1) ...
#9 9.113 Selecting previously unselected package libpango-1.0-0:amd64.
#9 9.114 Preparing to unpack .../063-libpango-1.0-0_1.56.3-1_amd64.deb ...
#9 9.115 Unpacking libpango-1.0-0:amd64 (1.56.3-1) ...
#9 9.138 Selecting previously unselected package libpangoft2-1.0-0:amd64.
#9 9.139 Preparing to unpack .../064-libpangoft2-1.0-0_1.56.3-1_amd64.deb ...
#9 9.140 Unpacking libpangoft2-1.0-0:amd64 (1.56.3-1) ...
#9 9.156 Selecting previously unselected package libpangocairo-1.0-0:amd64.
#9 9.157 Preparing to unpack .../065-libpangocairo-1.0-0_1.56.3-1_amd64.deb ...
#9 9.158 Unpacking libpangocairo-1.0-0:amd64 (1.56.3-1) ...
#9 9.174 Selecting previously unselected package librsvg2-2:amd64.
#9 9.175 Preparing to unpack .../066-librsvg2-2_2.60.0+dfsg-1_amd64.deb ...
#9 9.176 Unpacking librsvg2-2:amd64 (2.60.0+dfsg-1) ...
#9 9.263 Selecting previously unselected package libshine3:amd64.
#9 9.265 Preparing to unpack .../067-libshine3_3.1.1-2+b2_amd64.deb ...
#9 9.266 Unpacking libshine3:amd64 (3.1.1-2+b2) ...
#9 9.281 Selecting previously unselected package libsnappy1v5:amd64.
#9 9.282 Preparing to unpack .../068-libsnappy1v5_1.2.2-1_amd64.deb ...
#9 9.283 Unpacking libsnappy1v5:amd64 (1.2.2-1) ...
#9 9.299 Selecting previously unselected package libspeex1:amd64.
#9 9.300 Preparing to unpack .../069-libspeex1_1.2.1-3_amd64.deb ...
#9 9.301 Unpacking libspeex1:amd64 (1.2.1-3) ...
#9 9.318 Selecting previously unselected package libsvtav1enc2:amd64.
#9 9.319 Preparing to unpack .../070-libsvtav1enc2_2.3.0+dfsg-1_amd64.deb ...
#9 9.320 Unpacking libsvtav1enc2:amd64 (2.3.0+dfsg-1) ...
#9 9.433 Selecting previously unselected package libgomp1:amd64.
#9 9.434 Preparing to unpack .../071-libgomp1_14.2.0-19_amd64.deb ...
#9 9.435 Unpacking libgomp1:amd64 (14.2.0-19) ...
#9 9.455 Selecting previously unselected package libsoxr0:amd64.
#9 9.456 Preparing to unpack .../072-libsoxr0_0.1.3-4+b2_amd64.deb ...
#9 9.457 Unpacking libsoxr0:amd64 (0.1.3-4+b2) ...
#9 9.475 Selecting previously unselected package libswresample5:amd64.
#9 9.476 Preparing to unpack .../073-libswresample5_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 9.477 Unpacking libswresample5:amd64 (7:7.1.3-0+deb13u1) ...
#9 9.495 Selecting previously unselected package libtheoradec1:amd64.
#9 9.496 Preparing to unpack .../074-libtheoradec1_1.2.0~alpha1+dfsg-6_amd64.deb ...
#9 9.497 Unpacking libtheoradec1:amd64 (1.2.0~alpha1+dfsg-6) ...
#9 9.514 Selecting previously unselected package libogg0:amd64.
#9 9.515 Preparing to unpack .../075-libogg0_1.3.5-3+b2_amd64.deb ...
#9 9.516 Unpacking libogg0:amd64 (1.3.5-3+b2) ...
#9 9.532 Selecting previously unselected package libtheoraenc1:amd64.
#9 9.533 Preparing to unpack .../076-libtheoraenc1_1.2.0~alpha1+dfsg-6_amd64.deb ...
#9 9.534 Unpacking libtheoraenc1:amd64 (1.2.0~alpha1+dfsg-6) ...
#9 9.553 Selecting previously unselected package libtwolame0:amd64.
#9 9.553 Preparing to unpack .../077-libtwolame0_0.4.0-2+b2_amd64.deb ...
#9 9.554 Unpacking libtwolame0:amd64 (0.4.0-2+b2) ...
#9 9.572 Selecting previously unselected package libvorbis0a:amd64.
#9 9.573 Preparing to unpack .../078-libvorbis0a_1.3.7-3_amd64.deb ...
#9 9.573 Unpacking libvorbis0a:amd64 (1.3.7-3) ...
#9 9.592 Selecting previously unselected package libvorbisenc2:amd64.
#9 9.593 Preparing to unpack .../079-libvorbisenc2_1.3.7-3_amd64.deb ...
#9 9.594 Unpacking libvorbisenc2:amd64 (1.3.7-3) ...
#9 9.614 Selecting previously unselected package libvpx9:amd64.
#9 9.615 Preparing to unpack .../080-libvpx9_1.15.0-2.1+deb13u1_amd64.deb ...
#9 9.616 Unpacking libvpx9:amd64 (1.15.0-2.1+deb13u1) ...
#9 9.673 Selecting previously unselected package libwebpmux3:amd64.
#9 9.674 Preparing to unpack .../081-libwebpmux3_1.5.0-0.1_amd64.deb ...
#9 9.675 Unpacking libwebpmux3:amd64 (1.5.0-0.1) ...
#9 9.693 Selecting previously unselected package libx264-164:amd64.
#9 9.694 Preparing to unpack .../082-libx264-164_2%3a0.164.3108+git31e19f9-2+b1_amd64.deb ...
#9 9.695 Unpacking libx264-164:amd64 (2:0.164.3108+git31e19f9-2+b1) ...
#9 9.733 Selecting previously unselected package libnuma1:amd64.
#9 9.734 Preparing to unpack .../083-libnuma1_2.0.19-1_amd64.deb ...
#9 9.744 Unpacking libnuma1:amd64 (2.0.19-1) ...
#9 9.762 Selecting previously unselected package libx265-215:amd64.
#9 9.763 Preparing to unpack .../084-libx265-215_4.1-2_amd64.deb ...
#9 9.764 Unpacking libx265-215:amd64 (4.1-2) ...
#9 9.850 Selecting previously unselected package libxvidcore4:amd64.
#9 9.851 Preparing to unpack .../085-libxvidcore4_2%3a1.3.7-1+b2_amd64.deb ...
#9 9.852 Unpacking libxvidcore4:amd64 (2:1.3.7-1+b2) ...
#9 9.876 Selecting previously unselected package libzvbi-common.
#9 9.878 Preparing to unpack .../086-libzvbi-common_0.2.44-1_all.deb ...
#9 9.879 Unpacking libzvbi-common (0.2.44-1) ...
#9 9.896 Selecting previously unselected package libzvbi0t64:amd64.
#9 9.897 Preparing to unpack .../087-libzvbi0t64_0.2.44-1_amd64.deb ...
#9 9.898 Unpacking libzvbi0t64:amd64 (0.2.44-1) ...
#9 9.924 Selecting previously unselected package libavcodec61:amd64.
#9 9.925 Preparing to unpack .../088-libavcodec61_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 9.926 Unpacking libavcodec61:amd64 (7:7.1.3-0+deb13u1) ...
#9 10.15 Selecting previously unselected package libasound2-data.
#9 10.15 Preparing to unpack .../089-libasound2-data_1.2.14-1_all.deb ...
#9 10.15 Unpacking libasound2-data (1.2.14-1) ...
#9 10.18 Selecting previously unselected package libasound2t64:amd64.
#9 10.18 Preparing to unpack .../090-libasound2t64_1.2.14-1_amd64.deb ...
#9 10.18 Unpacking libasound2t64:amd64 (1.2.14-1) ...
#9 10.21 Selecting previously unselected package libraw1394-11:amd64.
#9 10.21 Preparing to unpack .../091-libraw1394-11_2.1.2-2+b2_amd64.deb ...
#9 10.22 Unpacking libraw1394-11:amd64 (2.1.2-2+b2) ...
#9 10.23 Selecting previously unselected package libavc1394-0:amd64.
#9 10.23 Preparing to unpack .../092-libavc1394-0_0.5.4-5+b2_amd64.deb ...
#9 10.23 Unpacking libavc1394-0:amd64 (0.5.4-5+b2) ...
#9 10.25 Selecting previously unselected package libunibreak6:amd64.
#9 10.25 Preparing to unpack .../093-libunibreak6_6.1-3_amd64.deb ...
#9 10.25 Unpacking libunibreak6:amd64 (6.1-3) ...
#9 10.27 Selecting previously unselected package libass9:amd64.
#9 10.27 Preparing to unpack .../094-libass9_1%3a0.17.3-1+b1_amd64.deb ...
#9 10.27 Unpacking libass9:amd64 (1:0.17.3-1+b1) ...
#9 10.29 Selecting previously unselected package libudfread0:amd64.
#9 10.29 Preparing to unpack .../095-libudfread0_1.1.2-1+b2_amd64.deb ...
#9 10.29 Unpacking libudfread0:amd64 (1.1.2-1+b2) ...
#9 10.31 Selecting previously unselected package libbluray2:amd64.
#9 10.31 Preparing to unpack .../096-libbluray2_1%3a1.3.4-1+b2_amd64.deb ...
#9 10.31 Unpacking libbluray2:amd64 (1:1.3.4-1+b2) ...
#9 10.33 Selecting previously unselected package libchromaprint1:amd64.
#9 10.34 Preparing to unpack .../097-libchromaprint1_1.5.1-7_amd64.deb ...
#9 10.34 Unpacking libchromaprint1:amd64 (1.5.1-7) ...
#9 10.35 Selecting previously unselected package libdvdread8t64:amd64.
#9 10.36 Preparing to unpack .../098-libdvdread8t64_6.1.3-2_amd64.deb ...
#9 10.36 Unpacking libdvdread8t64:amd64 (6.1.3-2) ...
#9 10.38 Selecting previously unselected package libdvdnav4:amd64.
#9 10.38 Preparing to unpack .../099-libdvdnav4_6.1.1-3+b1_amd64.deb ...
#9 10.38 Unpacking libdvdnav4:amd64 (6.1.1-3+b1) ...
#9 10.40 Selecting previously unselected package libgme0:amd64.
#9 10.40 Preparing to unpack .../100-libgme0_0.6.3-7+b2_amd64.deb ...
#9 10.40 Unpacking libgme0:amd64 (0.6.3-7+b2) ...
#9 10.42 Selecting previously unselected package libunistring5:amd64.
#9 10.42 Preparing to unpack .../101-libunistring5_1.3-2_amd64.deb ...
#9 10.42 Unpacking libunistring5:amd64 (1.3-2) ...
#9 10.46 Selecting previously unselected package libidn2-0:amd64.
#9 10.46 Preparing to unpack .../102-libidn2-0_2.3.8-2_amd64.deb ...
#9 10.46 Unpacking libidn2-0:amd64 (2.3.8-2) ...
#9 10.48 Selecting previously unselected package libp11-kit0:amd64.
#9 10.49 Preparing to unpack .../103-libp11-kit0_0.25.5-3_amd64.deb ...
#9 10.49 Unpacking libp11-kit0:amd64 (0.25.5-3) ...
#9 10.52 Selecting previously unselected package libtasn1-6:amd64.
#9 10.52 Preparing to unpack .../104-libtasn1-6_4.20.0-2_amd64.deb ...
#9 10.52 Unpacking libtasn1-6:amd64 (4.20.0-2) ...
#9 10.54 Selecting previously unselected package libgnutls30t64:amd64.
#9 10.54 Preparing to unpack .../105-libgnutls30t64_3.8.9-3+deb13u2_amd64.deb ...
#9 10.54 Unpacking libgnutls30t64:amd64 (3.8.9-3+deb13u2) ...
#9 10.60 Selecting previously unselected package libmpg123-0t64:amd64.
#9 10.60 Preparing to unpack .../106-libmpg123-0t64_1.32.10-1_amd64.deb ...
#9 10.60 Unpacking libmpg123-0t64:amd64 (1.32.10-1) ...
#9 10.62 Selecting previously unselected package libvorbisfile3:amd64.
#9 10.62 Preparing to unpack .../107-libvorbisfile3_1.3.7-3_amd64.deb ...
#9 10.62 Unpacking libvorbisfile3:amd64 (1.3.7-3) ...
#9 10.64 Selecting previously unselected package libopenmpt0t64:amd64.
#9 10.64 Preparing to unpack .../108-libopenmpt0t64_0.7.13-1+b1_amd64.deb ...
#9 10.64 Unpacking libopenmpt0t64:amd64 (0.7.13-1+b1) ...
#9 10.69 Selecting previously unselected package librabbitmq4:amd64.
#9 10.69 Preparing to unpack .../109-librabbitmq4_0.15.0-1_amd64.deb ...
#9 10.69 Unpacking librabbitmq4:amd64 (0.15.0-1) ...
#9 10.71 Selecting previously unselected package libcjson1:amd64.
#9 10.71 Preparing to unpack .../110-libcjson1_1.7.18-3.1+deb13u1_amd64.deb ...
#9 10.71 Unpacking libcjson1:amd64 (1.7.18-3.1+deb13u1) ...
#9 10.73 Selecting previously unselected package libmbedcrypto16:amd64.
#9 10.73 Preparing to unpack .../111-libmbedcrypto16_3.6.5-0.1~deb13u1_amd64.deb ...
#9 10.73 Unpacking libmbedcrypto16:amd64 (3.6.5-0.1~deb13u1) ...
#9 10.75 Selecting previously unselected package librist4:amd64.
#9 10.76 Preparing to unpack .../112-librist4_0.2.11+dfsg-1_amd64.deb ...
#9 10.76 Unpacking librist4:amd64 (0.2.11+dfsg-1) ...
#9 10.77 Selecting previously unselected package libsrt1.5-gnutls:amd64.
#9 10.77 Preparing to unpack .../113-libsrt1.5-gnutls_1.5.4-1_amd64.deb ...
#9 10.79 Unpacking libsrt1.5-gnutls:amd64 (1.5.4-1) ...
#9 10.82 Selecting previously unselected package libkrb5support0:amd64.
#9 10.82 Preparing to unpack .../114-libkrb5support0_1.21.3-5_amd64.deb ...
#9 10.82 Unpacking libkrb5support0:amd64 (1.21.3-5) ...
#9 10.84 Selecting previously unselected package libcom-err2:amd64.
#9 10.84 Preparing to unpack .../115-libcom-err2_1.47.2-3+b7_amd64.deb ...
#9 10.84 Unpacking libcom-err2:amd64 (1.47.2-3+b7) ...
#9 10.85 Selecting previously unselected package libk5crypto3:amd64.
#9 10.86 Preparing to unpack .../116-libk5crypto3_1.21.3-5_amd64.deb ...
#9 10.86 Unpacking libk5crypto3:amd64 (1.21.3-5) ...
#9 10.88 Selecting previously unselected package libkeyutils1:amd64.
#9 10.88 Preparing to unpack .../117-libkeyutils1_1.6.3-6_amd64.deb ...
#9 10.88 Unpacking libkeyutils1:amd64 (1.6.3-6) ...
#9 10.89 Selecting previously unselected package libkrb5-3:amd64.
#9 10.89 Preparing to unpack .../118-libkrb5-3_1.21.3-5_amd64.deb ...
#9 10.90 Unpacking libkrb5-3:amd64 (1.21.3-5) ...
#9 10.93 Selecting previously unselected package libgssapi-krb5-2:amd64.
#9 10.93 Preparing to unpack .../119-libgssapi-krb5-2_1.21.3-5_amd64.deb ...
#9 10.93 Unpacking libgssapi-krb5-2:amd64 (1.21.3-5) ...
#9 10.95 Selecting previously unselected package libssh-4:amd64.
#9 10.95 Preparing to unpack .../120-libssh-4_0.11.2-1+deb13u1_amd64.deb ...
#9 10.95 Unpacking libssh-4:amd64 (0.11.2-1+deb13u1) ...
#9 10.97 Selecting previously unselected package libnorm1t64:amd64.
#9 10.98 Preparing to unpack .../121-libnorm1t64_1.5.9+dfsg-3.1+b2_amd64.deb ...
#9 10.98 Unpacking libnorm1t64:amd64 (1.5.9+dfsg-3.1+b2) ...
#9 11.00 Selecting previously unselected package libpgm-5.3-0t64:amd64.
#9 11.00 Preparing to unpack .../122-libpgm-5.3-0t64_5.3.128~dfsg-2.1+b1_amd64.deb ...
#9 11.00 Unpacking libpgm-5.3-0t64:amd64 (5.3.128~dfsg-2.1+b1) ...
#9 11.02 Selecting previously unselected package libsodium23:amd64.
#9 11.03 Preparing to unpack .../123-libsodium23_1.0.18-1+deb13u1_amd64.deb ...
#9 11.03 Unpacking libsodium23:amd64 (1.0.18-1+deb13u1) ...
#9 11.05 Selecting previously unselected package libzmq5:amd64.
#9 11.05 Preparing to unpack .../124-libzmq5_4.3.5-1+b3_amd64.deb ...
#9 11.05 Unpacking libzmq5:amd64 (4.3.5-1+b3) ...
#9 11.08 Selecting previously unselected package libavformat61:amd64.
#9 11.08 Preparing to unpack .../125-libavformat61_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 11.08 Unpacking libavformat61:amd64 (7:7.1.3-0+deb13u1) ...
#9 11.14 Selecting previously unselected package libbs2b0:amd64.
#9 11.14 Preparing to unpack .../126-libbs2b0_3.1.0+dfsg-8+b1_amd64.deb ...
#9 11.14 Unpacking libbs2b0:amd64 (3.1.0+dfsg-8+b1) ...
#9 11.16 Selecting previously unselected package libflite1:amd64.
#9 11.16 Preparing to unpack .../127-libflite1_2.2-7_amd64.deb ...
#9 11.16 Unpacking libflite1:amd64 (2.2-7) ...
#9 11.58 Selecting previously unselected package libserd-0-0:amd64.
#9 11.58 Preparing to unpack .../128-libserd-0-0_0.32.4-1_amd64.deb ...
#9 11.58 Unpacking libserd-0-0:amd64 (0.32.4-1) ...
#9 11.60 Selecting previously unselected package libzix-0-0:amd64.
#9 11.60 Preparing to unpack .../129-libzix-0-0_0.6.2-1_amd64.deb ...
#9 11.60 Unpacking libzix-0-0:amd64 (0.6.2-1) ...
#9 11.61 Selecting previously unselected package libsord-0-0:amd64.
#9 11.62 Preparing to unpack .../130-libsord-0-0_0.16.18-1_amd64.deb ...
#9 11.62 Unpacking libsord-0-0:amd64 (0.16.18-1) ...
#9 11.63 Selecting previously unselected package libsratom-0-0:amd64.
#9 11.63 Preparing to unpack .../131-libsratom-0-0_0.6.18-1_amd64.deb ...
#9 11.64 Unpacking libsratom-0-0:amd64 (0.6.18-1) ...
#9 11.65 Selecting previously unselected package liblilv-0-0:amd64.
#9 11.65 Preparing to unpack .../132-liblilv-0-0_0.24.26-1_amd64.deb ...
#9 11.65 Unpacking liblilv-0-0:amd64 (0.24.26-1) ...
#9 11.67 Selecting previously unselected package libmysofa1:amd64.
#9 11.67 Preparing to unpack .../133-libmysofa1_1.3.3+dfsg-1_amd64.deb ...
#9 11.67 Unpacking libmysofa1:amd64 (1.3.3+dfsg-1) ...
#9 11.71 Selecting previously unselected package libvulkan1:amd64.
#9 11.71 Preparing to unpack .../134-libvulkan1_1.4.309.0-1_amd64.deb ...
#9 11.71 Unpacking libvulkan1:amd64 (1.4.309.0-1) ...
#9 11.73 Selecting previously unselected package libplacebo349:amd64.
#9 11.73 Preparing to unpack .../135-libplacebo349_7.349.0-3_amd64.deb ...
#9 11.73 Unpacking libplacebo349:amd64 (7.349.0-3) ...
#9 11.85 Selecting previously unselected package libblas3:amd64.
#9 11.85 Preparing to unpack .../136-libblas3_3.12.1-6_amd64.deb ...
#9 11.85 Unpacking libblas3:amd64 (3.12.1-6) ...
#9 11.88 Selecting previously unselected package libgfortran5:amd64.
#9 11.88 Preparing to unpack .../137-libgfortran5_14.2.0-19_amd64.deb ...
#9 11.88 Unpacking libgfortran5:amd64 (14.2.0-19) ...
#9 11.93 Selecting previously unselected package liblapack3:amd64.
#9 11.93 Preparing to unpack .../138-liblapack3_3.12.1-6_amd64.deb ...
#9 11.93 Unpacking liblapack3:amd64 (3.12.1-6) ...
#9 12.05 Selecting previously unselected package libasyncns0:amd64.
#9 12.05 Preparing to unpack .../139-libasyncns0_0.8-6+b5_amd64.deb ...
#9 12.05 Unpacking libasyncns0:amd64 (0.8-6+b5) ...
#9 12.07 Selecting previously unselected package libdbus-1-3:amd64.
#9 12.07 Preparing to unpack .../140-libdbus-1-3_1.16.2-2_amd64.deb ...
#9 12.07 Unpacking libdbus-1-3:amd64 (1.16.2-2) ...
#9 12.09 Selecting previously unselected package libflac14:amd64.
#9 12.09 Preparing to unpack .../141-libflac14_1.5.0+ds-2_amd64.deb ...
#9 12.10 Unpacking libflac14:amd64 (1.5.0+ds-2) ...
#9 12.12 Selecting previously unselected package libsndfile1:amd64.
#9 12.12 Preparing to unpack .../142-libsndfile1_1.2.2-2+b1_amd64.deb ...
#9 12.12 Unpacking libsndfile1:amd64 (1.2.2-2+b1) ...
#9 12.15 Selecting previously unselected package libpulse0:amd64.
#9 12.15 Preparing to unpack .../143-libpulse0_17.0+dfsg1-2+b1_amd64.deb ...
#9 12.15 Unpacking libpulse0:amd64 (17.0+dfsg1-2+b1) ...
#9 12.18 Selecting previously unselected package libsphinxbase3t64:amd64.
#9 12.18 Preparing to unpack .../144-libsphinxbase3t64_0.8+5prealpha+1-21+b1_amd64.deb ...
#9 12.18 Unpacking libsphinxbase3t64:amd64 (0.8+5prealpha+1-21+b1) ...
#9 12.20 Selecting previously unselected package libpocketsphinx3:amd64.
#9 12.20 Preparing to unpack .../145-libpocketsphinx3_0.8+5prealpha+1-15+b4_amd64.deb ...
#9 12.20 Unpacking libpocketsphinx3:amd64 (0.8+5prealpha+1-15+b4) ...
#9 12.23 Selecting previously unselected package libpostproc58:amd64.
#9 12.23 Preparing to unpack .../146-libpostproc58_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 12.23 Unpacking libpostproc58:amd64 (7:7.1.3-0+deb13u1) ...
#9 12.25 Selecting previously unselected package libfftw3-double3:amd64.
#9 12.25 Preparing to unpack .../147-libfftw3-double3_3.3.10-2+b1_amd64.deb ...
#9 12.25 Unpacking libfftw3-double3:amd64 (3.3.10-2+b1) ...
#9 12.30 Selecting previously unselected package libsamplerate0:amd64.
#9 12.30 Preparing to unpack .../148-libsamplerate0_0.2.2-4+b2_amd64.deb ...
#9 12.30 Unpacking libsamplerate0:amd64 (0.2.2-4+b2) ...
#9 12.35 Selecting previously unselected package librubberband2:amd64.
#9 12.36 Preparing to unpack .../149-librubberband2_3.3.0+dfsg-2+b3_amd64.deb ...
#9 12.36 Unpacking librubberband2:amd64 (3.3.0+dfsg-2+b3) ...
#9 12.38 Selecting previously unselected package libswscale8:amd64.
#9 12.38 Preparing to unpack .../150-libswscale8_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 12.38 Unpacking libswscale8:amd64 (7:7.1.3-0+deb13u1) ...
#9 12.41 Selecting previously unselected package libvidstab1.1:amd64.
#9 12.41 Preparing to unpack .../151-libvidstab1.1_1.1.0-2+b2_amd64.deb ...
#9 12.41 Unpacking libvidstab1.1:amd64 (1.1.0-2+b2) ...
#9 12.43 Selecting previously unselected package libzimg2:amd64.
#9 12.43 Preparing to unpack .../152-libzimg2_3.0.5+ds1-1+b2_amd64.deb ...
#9 12.43 Unpacking libzimg2:amd64 (3.0.5+ds1-1+b2) ...
#9 12.46 Selecting previously unselected package libavfilter10:amd64.
#9 12.46 Preparing to unpack .../153-libavfilter10_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 12.46 Unpacking libavfilter10:amd64 (7:7.1.3-0+deb13u1) ...
#9 12.63 Selecting previously unselected package libslang2:amd64.
#9 12.63 Preparing to unpack .../154-libslang2_2.3.3-5+b2_amd64.deb ...
#9 12.63 Unpacking libslang2:amd64 (2.3.3-5+b2) ...
#9 12.67 Selecting previously unselected package libcaca0:amd64.
#9 12.67 Preparing to unpack .../155-libcaca0_0.99.beta20-5_amd64.deb ...
#9 12.67 Unpacking libcaca0:amd64 (0.99.beta20-5) ...
#9 12.70 Selecting previously unselected package libcdio19t64:amd64.
#9 12.70 Preparing to unpack .../156-libcdio19t64_2.2.0-4_amd64.deb ...
#9 12.70 Unpacking libcdio19t64:amd64 (2.2.0-4) ...
#9 12.72 Selecting previously unselected package libcdio-cdda2t64:amd64.
#9 12.72 Preparing to unpack .../157-libcdio-cdda2t64_10.2+2.0.2-1+b1_amd64.deb ...
#9 12.73 Unpacking libcdio-cdda2t64:amd64 (10.2+2.0.2-1+b1) ...
#9 12.75 Selecting previously unselected package libcdio-paranoia2t64:amd64.
#9 12.75 Preparing to unpack .../158-libcdio-paranoia2t64_10.2+2.0.2-1+b1_amd64.deb ...
#9 12.76 Unpacking libcdio-paranoia2t64:amd64 (10.2+2.0.2-1+b1) ...
#9 12.77 Selecting previously unselected package libusb-1.0-0:amd64.
#9 12.77 Preparing to unpack .../159-libusb-1.0-0_2%3a1.0.28-1_amd64.deb ...
#9 12.77 Unpacking libusb-1.0-0:amd64 (2:1.0.28-1) ...
#9 12.79 Selecting previously unselected package libdc1394-25:amd64.
#9 12.79 Preparing to unpack .../160-libdc1394-25_2.2.6-5_amd64.deb ...
#9 12.79 Unpacking libdc1394-25:amd64 (2.2.6-5) ...
#9 12.81 Selecting previously unselected package libglvnd0:amd64.
#9 12.82 Preparing to unpack .../161-libglvnd0_1.7.0-1+b2_amd64.deb ...
#9 12.82 Unpacking libglvnd0:amd64 (1.7.0-1+b2) ...
#9 12.84 Selecting previously unselected package libxcb-glx0:amd64.
#9 12.84 Preparing to unpack .../162-libxcb-glx0_1.17.0-2+b1_amd64.deb ...
#9 12.84 Unpacking libxcb-glx0:amd64 (1.17.0-2+b1) ...
#9 12.86 Selecting previously unselected package libxcb-present0:amd64.
#9 12.86 Preparing to unpack .../163-libxcb-present0_1.17.0-2+b1_amd64.deb ...
#9 12.86 Unpacking libxcb-present0:amd64 (1.17.0-2+b1) ...
#9 12.88 Selecting previously unselected package libxcb-xfixes0:amd64.
#9 12.88 Preparing to unpack .../164-libxcb-xfixes0_1.17.0-2+b1_amd64.deb ...
#9 12.88 Unpacking libxcb-xfixes0:amd64 (1.17.0-2+b1) ...
#9 12.90 Selecting previously unselected package libxxf86vm1:amd64.
#9 12.90 Preparing to unpack .../165-libxxf86vm1_1%3a1.1.4-1+b4_amd64.deb ...
#9 12.91 Unpacking libxxf86vm1:amd64 (1:1.1.4-1+b4) ...
#9 12.92 Selecting previously unselected package libdrm-amdgpu1:amd64.
#9 12.92 Preparing to unpack .../166-libdrm-amdgpu1_2.4.124-2_amd64.deb ...
#9 12.92 Unpacking libdrm-amdgpu1:amd64 (2.4.124-2) ...
#9 12.95 Selecting previously unselected package libpciaccess0:amd64.
#9 12.95 Preparing to unpack .../167-libpciaccess0_0.17-3+b3_amd64.deb ...
#9 12.95 Unpacking libpciaccess0:amd64 (0.17-3+b3) ...
#9 12.97 Selecting previously unselected package libdrm-intel1:amd64.
#9 12.98 Preparing to unpack .../168-libdrm-intel1_2.4.124-2_amd64.deb ...
#9 12.98 Unpacking libdrm-intel1:amd64 (2.4.124-2) ...
#9 13.00 Selecting previously unselected package libelf1t64:amd64.
#9 13.00 Preparing to unpack .../169-libelf1t64_0.192-4_amd64.deb ...
#9 13.00 Unpacking libelf1t64:amd64 (0.192-4) ...
#9 13.02 Selecting previously unselected package libedit2:amd64.
#9 13.03 Preparing to unpack .../170-libedit2_3.1-20250104-1_amd64.deb ...
#9 13.03 Unpacking libedit2:amd64 (3.1-20250104-1) ...
#9 13.05 Selecting previously unselected package libz3-4:amd64.
#9 13.05 Preparing to unpack .../171-libz3-4_4.13.3-1_amd64.deb ...
#9 13.05 Unpacking libz3-4:amd64 (4.13.3-1) ...
#9 13.37 Selecting previously unselected package libllvm19:amd64.
#9 13.37 Preparing to unpack .../172-libllvm19_1%3a19.1.7-3+b1_amd64.deb ...
#9 13.37 Unpacking libllvm19:amd64 (1:19.1.7-3+b1) ...
#9 14.01 Selecting previously unselected package libsensors-config.
#9 14.01 Preparing to unpack .../173-libsensors-config_1%3a3.6.2-2_all.deb ...
#9 14.01 Unpacking libsensors-config (1:3.6.2-2) ...
#9 14.03 Selecting previously unselected package libsensors5:amd64.
#9 14.03 Preparing to unpack .../174-libsensors5_1%3a3.6.2-2_amd64.deb ...
#9 14.03 Unpacking libsensors5:amd64 (1:3.6.2-2) ...
#9 14.05 Selecting previously unselected package libxcb-randr0:amd64.
#9 14.05 Preparing to unpack .../175-libxcb-randr0_1.17.0-2+b1_amd64.deb ...
#9 14.05 Unpacking libxcb-randr0:amd64 (1.17.0-2+b1) ...
#9 14.07 Selecting previously unselected package libxcb-sync1:amd64.
#9 14.07 Preparing to unpack .../176-libxcb-sync1_1.17.0-2+b1_amd64.deb ...
#9 14.07 Unpacking libxcb-sync1:amd64 (1.17.0-2+b1) ...
#9 14.09 Selecting previously unselected package libxshmfence1:amd64.
#9 14.09 Preparing to unpack .../177-libxshmfence1_1.3.3-1_amd64.deb ...
#9 14.09 Unpacking libxshmfence1:amd64 (1.3.3-1) ...
#9 14.11 Selecting previously unselected package mesa-libgallium:amd64.
#9 14.11 Preparing to unpack .../178-mesa-libgallium_25.0.7-2_amd64.deb ...
#9 14.11 Unpacking mesa-libgallium:amd64 (25.0.7-2) ...
#9 14.47 Selecting previously unselected package libwayland-server0:amd64.
#9 14.47 Preparing to unpack .../179-libwayland-server0_1.23.1-3_amd64.deb ...
#9 14.47 Unpacking libwayland-server0:amd64 (1.23.1-3) ...
#9 14.49 Selecting previously unselected package libgbm1:amd64.
#9 14.49 Preparing to unpack .../180-libgbm1_25.0.7-2_amd64.deb ...
#9 14.49 Unpacking libgbm1:amd64 (25.0.7-2) ...
#9 14.51 Selecting previously unselected package libgl1-mesa-dri:amd64.
#9 14.51 Preparing to unpack .../181-libgl1-mesa-dri_25.0.7-2_amd64.deb ...
#9 14.52 Unpacking libgl1-mesa-dri:amd64 (25.0.7-2) ...
#9 14.54 Selecting previously unselected package libglx-mesa0:amd64.
#9 14.54 Preparing to unpack .../182-libglx-mesa0_25.0.7-2_amd64.deb ...
#9 14.54 Unpacking libglx-mesa0:amd64 (25.0.7-2) ...
#9 14.56 Selecting previously unselected package libglx0:amd64.
#9 14.56 Preparing to unpack .../183-libglx0_1.7.0-1+b2_amd64.deb ...
#9 14.56 Unpacking libglx0:amd64 (1.7.0-1+b2) ...
#9 14.58 Selecting previously unselected package libgl1:amd64.
#9 14.59 Preparing to unpack .../184-libgl1_1.7.0-1+b2_amd64.deb ...
#9 14.59 Unpacking libgl1:amd64 (1.7.0-1+b2) ...
#9 14.61 Selecting previously unselected package libiec61883-0:amd64.
#9 14.61 Preparing to unpack .../185-libiec61883-0_1.2.0-7_amd64.deb ...
#9 14.61 Unpacking libiec61883-0:amd64 (1.2.0-7) ...
#9 14.63 Selecting previously unselected package libjack-jackd2-0:amd64.
#9 14.63 Preparing to unpack .../186-libjack-jackd2-0_1.9.22~dfsg-4_amd64.deb ...
#9 14.63 Unpacking libjack-jackd2-0:amd64 (1.9.22~dfsg-4) ...
#9 14.66 Selecting previously unselected package libopenal-data.
#9 14.66 Preparing to unpack .../187-libopenal-data_1%3a1.24.2-1_all.deb ...
#9 14.66 Unpacking libopenal-data (1:1.24.2-1) ...
#9 14.69 Selecting previously unselected package libopenal1:amd64.
#9 14.69 Preparing to unpack .../188-libopenal1_1%3a1.24.2-1_amd64.deb ...
#9 14.69 Unpacking libopenal1:amd64 (1:1.24.2-1) ...
#9 14.73 Selecting previously unselected package libwayland-client0:amd64.
#9 14.73 Preparing to unpack .../189-libwayland-client0_1.23.1-3_amd64.deb ...
#9 14.73 Unpacking libwayland-client0:amd64 (1.23.1-3) ...
#9 14.75 Selecting previously unselected package libdecor-0-0:amd64.
#9 14.75 Preparing to unpack .../190-libdecor-0-0_0.2.2-2_amd64.deb ...
#9 14.75 Unpacking libdecor-0-0:amd64 (0.2.2-2) ...
#9 14.77 Selecting previously unselected package libwayland-cursor0:amd64.
#9 14.77 Preparing to unpack .../191-libwayland-cursor0_1.23.1-3_amd64.deb ...
#9 14.77 Unpacking libwayland-cursor0:amd64 (1.23.1-3) ...
#9 14.79 Selecting previously unselected package libwayland-egl1:amd64.
#9 14.79 Preparing to unpack .../192-libwayland-egl1_1.23.1-3_amd64.deb ...
#9 14.79 Unpacking libwayland-egl1:amd64 (1.23.1-3) ...
#9 14.81 Selecting previously unselected package libxcursor1:amd64.
#9 14.81 Preparing to unpack .../193-libxcursor1_1%3a1.2.3-1_amd64.deb ...
#9 14.81 Unpacking libxcursor1:amd64 (1:1.2.3-1) ...
#9 14.83 Selecting previously unselected package libxi6:amd64.
#9 14.83 Preparing to unpack .../194-libxi6_2%3a1.8.2-1_amd64.deb ...
#9 14.83 Unpacking libxi6:amd64 (2:1.8.2-1) ...
#9 14.85 Selecting previously unselected package xkb-data.
#9 14.85 Preparing to unpack .../195-xkb-data_2.42-1_all.deb ...
#9 14.85 Unpacking xkb-data (2.42-1) ...
#9 14.93 Selecting previously unselected package libxkbcommon0:amd64.
#9 14.93 Preparing to unpack .../196-libxkbcommon0_1.7.0-2_amd64.deb ...
#9 14.93 Unpacking libxkbcommon0:amd64 (1.7.0-2) ...
#9 14.95 Selecting previously unselected package libxrandr2:amd64.
#9 14.96 Preparing to unpack .../197-libxrandr2_2%3a1.5.4-1+b3_amd64.deb ...
#9 14.96 Unpacking libxrandr2:amd64 (2:1.5.4-1+b3) ...
#9 14.98 Selecting previously unselected package x11-common.
#9 14.98 Preparing to unpack .../198-x11-common_1%3a7.7+24+deb13u1_all.deb ...
#9 14.98 Unpacking x11-common (1:7.7+24+deb13u1) ...
#9 15.00 Selecting previously unselected package libxss1:amd64.
#9 15.00 Preparing to unpack .../199-libxss1_1%3a1.2.3-1+b3_amd64.deb ...
#9 15.00 Unpacking libxss1:amd64 (1:1.2.3-1+b3) ...
#9 15.02 Selecting previously unselected package libsdl2-2.0-0:amd64.
#9 15.02 Preparing to unpack .../200-libsdl2-2.0-0_2.32.4+dfsg-1_amd64.deb ...
#9 15.02 Unpacking libsdl2-2.0-0:amd64 (2.32.4+dfsg-1) ...
#9 15.07 Selecting previously unselected package libxcb-shape0:amd64.
#9 15.07 Preparing to unpack .../201-libxcb-shape0_1.17.0-2+b1_amd64.deb ...
#9 15.07 Unpacking libxcb-shape0:amd64 (1.17.0-2+b1) ...
#9 15.09 Selecting previously unselected package libxv1:amd64.
#9 15.09 Preparing to unpack .../202-libxv1_2%3a1.0.11-1.1+b3_amd64.deb ...
#9 15.09 Unpacking libxv1:amd64 (2:1.0.11-1.1+b3) ...
#9 15.11 Selecting previously unselected package libavdevice61:amd64.
#9 15.11 Preparing to unpack .../203-libavdevice61_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 15.11 Unpacking libavdevice61:amd64 (7:7.1.3-0+deb13u1) ...
#9 15.13 Selecting previously unselected package ffmpeg.
#9 15.13 Preparing to unpack .../204-ffmpeg_7%3a7.1.3-0+deb13u1_amd64.deb ...
#9 15.13 Unpacking ffmpeg (7:7.1.3-0+deb13u1) ...
#9 15.20 Setting up libgme0:amd64 (0.6.3-7+b2) ...
#9 15.20 Setting up libchromaprint1:amd64 (1.5.1-7) ...
#9 15.21 Setting up libhwy1t64:amd64 (1.2.0-2+b2) ...
#9 15.21 Setting up libexpat1:amd64 (2.7.1-2) ...
#9 15.21 Setting up libgraphite2-3:amd64 (1.3.14-2+b1) ...
#9 15.21 Setting up liblcms2-2:amd64 (2.16-2) ...
#9 15.22 Setting up libpixman-1-0:amd64 (0.44.0-3) ...
#9 15.22 Setting up libdvdread8t64:amd64 (6.1.3-2) ...
#9 15.22 Setting up libudfread0:amd64 (1.1.2-1+b2) ...
#9 15.22 Setting up libnorm1t64:amd64 (1.5.9+dfsg-3.1+b2) ...
#9 15.23 Setting up libsharpyuv0:amd64 (1.5.0-0.1) ...
#9 15.23 Setting up libwayland-server0:amd64 (1.23.1-3) ...
#9 15.23 Setting up libaom3:amd64 (3.12.1-1) ...
#9 15.23 Setting up libpciaccess0:amd64 (0.17-3+b3) ...
#9 15.24 Setting up librabbitmq4:amd64 (0.15.0-1) ...
#9 15.24 Setting up libxau6:amd64 (1:1.0.11-1) ...
#9 15.24 Setting up libxdmcp6:amd64 (1:1.1.5-1) ...
#9 15.24 Setting up libraw1394-11:amd64 (2.1.2-2+b2) ...
#9 15.25 Setting up libkeyutils1:amd64 (1.6.3-6) ...
#9 15.25 Setting up libxcb1:amd64 (1.17.0-2+b1) ...
#9 15.25 Setting up libsodium23:amd64 (1.0.18-1+deb13u1) ...
#9 15.25 Setting up libxcb-xfixes0:amd64 (1.17.0-2+b1) ...
#9 15.26 Setting up libogg0:amd64 (1.3.5-3+b2) ...
#9 15.26 Setting up liblerc4:amd64 (4.0.0+ds-5) ...
#9 15.26 Setting up libspeex1:amd64 (1.2.1-3) ...
#9 15.26 Setting up libshine3:amd64 (3.1.1-2+b2) ...
#9 15.27 Setting up libvpl2 (1:2.14.0-1+b1) ...
#9 15.27 Setting up libx264-164:amd64 (2:0.164.3108+git31e19f9-2+b1) ...
#9 15.27 Setting up libtwolame0:amd64 (0.4.0-2+b2) ...
#9 15.27 Setting up libdatrie1:amd64 (0.2.13-3+b1) ...
#9 15.28 Setting up libgsm1:amd64 (1.0.22-1+b2) ...
#9 15.28 Setting up libxcb-render0:amd64 (1.17.0-2+b1) ...
#9 15.28 Setting up libzix-0-0:amd64 (0.6.2-1) ...
#9 15.28 Setting up libglvnd0:amd64 (1.7.0-1+b2) ...
#9 15.29 Setting up libcodec2-1.2:amd64 (1.2.0-3) ...
#9 15.29 Setting up libxcb-glx0:amd64 (1.17.0-2+b1) ...
#9 15.29 Setting up libbrotli1:amd64 (1.1.0-2+b7) ...
#9 15.29 Setting up libedit2:amd64 (3.1-20250104-1) ...
#9 15.30 Setting up libgdk-pixbuf2.0-common (2.42.12+dfsg-4) ...
#9 15.30 Setting up libmysofa1:amd64 (1.3.3+dfsg-1) ...
#9 15.31 Setting up libxcb-shape0:amd64 (1.17.0-2+b1) ...
#9 15.31 Setting up x11-common (1:7.7+24+deb13u1) ...
#9 15.38 debconf: unable to initialize frontend: Dialog
#9 15.38 debconf: (TERM is not set, so the dialog frontend is not usable.)
#9 15.38 debconf: falling back to frontend: Readline
#9 15.38 debconf: unable to initialize frontend: Readline
#9 15.38 debconf: (Can't locate Term/ReadLine.pm in @INC (you may need to install the Term::ReadLine module) (@INC entries checked: /etc/perl /usr/local/lib/x86_64-linux-gnu/perl/5.40.1 /usr/local/share/perl/5.40.1 /usr/lib/x86_64-linux-gnu/perl5/5.40 /usr/share/perl5 /usr/lib/x86_64-linux-gnu/perl-base /usr/lib/x86_64-linux-gnu/perl/5.40 /usr/share/perl/5.40 /usr/local/lib/site_perl) at /usr/share/perl5/Debconf/FrontEnd/Readline.pm line 8.)
#9 15.38 debconf: falling back to frontend: Teletype
#9 15.39 debconf: unable to initialize frontend: Teletype
#9 15.39 debconf: (This frontend requires a controlling tty.)
#9 15.39 debconf: falling back to frontend: Noninteractive
#9 15.40 invoke-rc.d: could not determine current runlevel
#9 15.40 invoke-rc.d: policy-rc.d denied execution of start.
#9 15.41 Setting up libsensors-config (1:3.6.2-2) ...
#9 15.41 Setting up libcdio19t64:amd64 (2.2.0-4) ...
#9 15.42 Setting up libdeflate0:amd64 (1.23-2) ...
#9 15.42 Setting up xkb-data (2.42-1) ...
#9 15.42 Setting up libxcb-shm0:amd64 (1.17.0-2+b1) ...
#9 15.42 Setting up libcom-err2:amd64 (1.47.2-3+b7) ...
#9 15.43 Setting up libmpg123-0t64:amd64 (1.32.10-1) ...
#9 15.43 Setting up libgomp1:amd64 (14.2.0-19) ...
#9 15.43 Setting up libcjson1:amd64 (1.7.18-3.1+deb13u1) ...
#9 15.44 Setting up libxvidcore4:amd64 (2:1.3.7-1+b2) ...
#9 15.44 Setting up libjbig0:amd64 (2.1-6.1+b2) ...
#9 15.44 Setting up libelf1t64:amd64 (0.192-4) ...
#9 15.44 Setting up libsnappy1v5:amd64 (1.2.2-1) ...
#9 15.45 Setting up libcdio-cdda2t64:amd64 (10.2+2.0.2-1+b1) ...
#9 15.45 Setting up libkrb5support0:amd64 (1.21.3-5) ...
#9 15.45 Setting up libxcb-present0:amd64 (1.17.0-2+b1) ...
#9 15.45 Setting up libasound2-data (1.2.14-1) ...
#9 15.46 Setting up libpgm-5.3-0t64:amd64 (5.3.128~dfsg-2.1+b1) ...
#9 15.46 Setting up libtheoraenc1:amd64 (1.2.0~alpha1+dfsg-6) ...
#9 15.46 Setting up libz3-4:amd64 (4.13.3-1) ...
#9 15.47 Setting up libblas3:amd64 (3.12.1-6) ...
#9 15.47 update-alternatives: using /usr/lib/x86_64-linux-gnu/blas/libblas.so.3 to provide /usr/lib/x86_64-linux-gnu/libblas.so.3 (libblas.so.3-x86_64-linux-gnu) in auto mode
#9 15.47 Setting up libasound2t64:amd64 (1.2.14-1) ...
#9 15.47 Setting up libjpeg62-turbo:amd64 (1:2.1.5-4) ...
#9 15.48 Setting up libslang2:amd64 (2.3.3-5+b2) ...
#9 15.48 Setting up libva2:amd64 (2.22.0-3) ...
#9 15.48 Setting up libx11-data (2:1.8.12-1) ...
#9 15.48 Setting up libsvtav1enc2:amd64 (2.3.0+dfsg-1) ...
#9 15.49 Setting up libxcb-sync1:amd64 (1.17.0-2+b1) ...
#9 15.49 Setting up libdbus-1-3:amd64 (1.16.2-2) ...
#9 15.49 Setting up libfribidi0:amd64 (1.0.16-1) ...
#9 15.50 Setting up libopus0:amd64 (1.5.2-2) ...
#9 15.50 Setting up libp11-kit0:amd64 (0.25.5-3) ...
#9 15.50 Setting up libcdio-paranoia2t64:amd64 (10.2+2.0.2-1+b1) ...
#9 15.50 Setting up libunistring5:amd64 (1.3-2) ...
#9 15.51 Setting up fonts-dejavu-mono (2.37-8) ...
#9 15.52 Setting up libpng16-16t64:amd64 (1.6.48-1+deb13u3) ...
#9 15.52 Setting up libatomic1:amd64 (14.2.0-19) ...
#9 15.53 Setting up libvorbis0a:amd64 (1.3.7-3) ...
#9 15.53 Setting up fonts-dejavu-core (2.37-8) ...
#9 15.55 Setting up libflac14:amd64 (1.5.0+ds-2) ...
#9 15.56 Setting up libsensors5:amd64 (1:3.6.2-2) ...
#9 15.56 Setting up libk5crypto3:amd64 (1.21.3-5) ...
#9 15.56 Setting up libfftw3-double3:amd64 (3.3.10-2+b1) ...
#9 15.56 Setting up libgfortran5:amd64 (14.2.0-19) ...
#9 15.57 Setting up libvulkan1:amd64 (1.4.309.0-1) ...
#9 15.57 Setting up libwebp7:amd64 (1.5.0-0.1) ...
#9 15.57 Setting up libnuma1:amd64 (2.0.19-1) ...
#9 15.57 Setting up libvidstab1.1:amd64 (1.1.0-2+b2) ...
#9 15.58 Setting up libvpx9:amd64 (1.15.0-2.1+deb13u1) ...
#9 15.58 Setting up libflite1:amd64 (2.2-7) ...
#9 15.58 Setting up libdav1d7:amd64 (1.5.1-1) ...
#9 15.58 Setting up ocl-icd-libopencl1:amd64 (2.3.3-1) ...
#9 15.59 Setting up libasyncns0:amd64 (0.8-6+b5) ...
#9 15.59 Setting up libxshmfence1:amd64 (1.3.3-1) ...
#9 15.59 Setting up libtiff6:amd64 (4.7.0-3+deb13u1) ...
#9 15.59 Setting up libbs2b0:amd64 (3.1.0+dfsg-8+b1) ...
#9 15.59 Setting up libxcb-randr0:amd64 (1.17.0-2+b1) ...
#9 15.60 Setting up librav1e0.7:amd64 (0.7.1-9+b2) ...
#9 15.60 Setting up libtasn1-6:amd64 (4.20.0-2) ...
#9 15.60 Setting up libzimg2:amd64 (3.0.5+ds1-1+b2) ...
#9 15.61 Setting up libopenjp2-7:amd64 (2.5.3-2.1~deb13u1) ...
#9 15.61 Setting up libx11-6:amd64 (2:1.8.12-1) ...
#9 15.61 Setting up libopenal-data (1:1.24.2-1) ...
#9 15.61 Setting up libthai-data (0.1.29-2) ...
#9 15.62 Setting up libkrb5-3:amd64 (1.21.3-5) ...
#9 15.62 Setting up libunibreak6:amd64 (6.1-3) ...
#9 15.62 Setting up libwayland-egl1:amd64 (1.23.1-3) ...
#9 15.62 Setting up libusb-1.0-0:amd64 (2:1.0.28-1) ...
#9 15.63 Setting up libmbedcrypto16:amd64 (3.6.5-0.1~deb13u1) ...
#9 15.63 Setting up libx265-215:amd64 (4.1-2) ...
#9 15.63 Setting up libsamplerate0:amd64 (0.2.2-4+b2) ...
#9 15.63 Setting up libwebpmux3:amd64 (1.5.0-0.1) ...
#9 15.63 Setting up libdrm-common (2.4.124-2) ...
#9 15.64 Setting up libjxl0.11:amd64 (0.11.1-4) ...
#9 15.64 Setting up libxml2:amd64 (2.12.7+dfsg+really2.9.14-2.1+deb13u2) ...
#9 15.64 Setting up libzvbi-common (0.2.44-1) ...
#9 15.64 Setting up libmp3lame0:amd64 (3.100-6+b3) ...
#9 15.65 Setting up libvorbisenc2:amd64 (1.3.7-3) ...
#9 15.65 Setting up libdvdnav4:amd64 (6.1.1-3+b1) ...
#9 15.66 Setting up libiec61883-0:amd64 (1.2.0-7) ...
#9 15.66 Setting up libserd-0-0:amd64 (0.32.4-1) ...
#9 15.66 Setting up libxkbcommon0:amd64 (1.7.0-2) ...
#9 15.66 Setting up libwayland-client0:amd64 (1.23.1-3) ...
#9 15.67 Setting up libavc1394-0:amd64 (0.5.4-5+b2) ...
#9 15.67 Setting up libxcb-dri3-0:amd64 (1.17.0-2+b1) ...
#9 15.67 Setting up libllvm19:amd64 (1:19.1.7-3+b1) ...
#9 15.67 Setting up libx11-xcb1:amd64 (2:1.8.12-1) ...
#9 15.68 Setting up liblapack3:amd64 (3.12.1-6) ...
#9 15.68 update-alternatives: using /usr/lib/x86_64-linux-gnu/lapack/liblapack.so.3 to provide /usr/lib/x86_64-linux-gnu/liblapack.so.3 (liblapack.so.3-x86_64-linux-gnu) in auto mode
#9 15.68 Setting up libcaca0:amd64 (0.99.beta20-5) ...
#9 15.68 Setting up libzvbi0t64:amd64 (0.2.44-1) ...
#9 15.69 Setting up libxrender1:amd64 (1:0.9.12-1) ...
#9 15.69 Setting up libsoxr0:amd64 (0.1.3-4+b2) ...
#9 15.69 Setting up fontconfig-config (2.15.0-2.3) ...
#9 15.76 debconf: unable to initialize frontend: Dialog
#9 15.76 debconf: (TERM is not set, so the dialog frontend is not usable.)
#9 15.76 debconf: falling back to frontend: Readline
#9 15.76 debconf: unable to initialize frontend: Readline
#9 15.76 debconf: (Can't locate Term/ReadLine.pm in @INC (you may need to install the Term::ReadLine module) (@INC entries checked: /etc/perl /usr/local/lib/x86_64-linux-gnu/perl/5.40.1 /usr/local/share/perl/5.40.1 /usr/lib/x86_64-linux-gnu/perl5/5.40 /usr/share/perl5 /usr/lib/x86_64-linux-gnu/perl-base /usr/lib/x86_64-linux-gnu/perl/5.40 /usr/share/perl/5.40 /usr/local/lib/site_perl) at /usr/share/perl5/Debconf/FrontEnd/Readline.pm line 8.)
#9 15.76 debconf: falling back to frontend: Teletype
#9 15.76 debconf: unable to initialize frontend: Teletype
#9 15.76 debconf: (This frontend requires a controlling tty.)
#9 15.76 debconf: falling back to frontend: Noninteractive
#9 15.80 Setting up libxext6:amd64 (2:1.3.4-1+b3) ...
#9 15.80 Setting up libidn2-0:amd64 (2.3.8-2) ...
#9 15.80 Setting up libopenal1:amd64 (1:1.24.2-1) ...
#9 15.80 Setting up libxxf86vm1:amd64 (1:1.1.4-1+b4) ...
#9 15.81 Setting up librist4:amd64 (0.2.11+dfsg-1) ...
#9 15.81 Setting up libthai0:amd64 (0.1.29-2+b1) ...
#9 15.81 Setting up libvorbisfile3:amd64 (1.3.7-3) ...
#9 15.81 Setting up libglib2.0-0t64:amd64 (2.84.4-3~deb13u2) ...
#9 15.82 No schema files found: doing nothing.
#9 15.82 Setting up libfreetype6:amd64 (2.13.3+dfsg-1) ...
#9 15.83 Setting up libxfixes3:amd64 (1:6.0.0-2+b4) ...
#9 15.83 Setting up shared-mime-info (2.4-5+b2) ...
#9 16.50 Setting up libplacebo349:amd64 (7.349.0-3) ...
#9 16.50 Setting up libdc1394-25:amd64 (2.2.6-5) ...
#9 16.51 Setting up libxv1:amd64 (2:1.0.11-1.1+b3) ...
#9 16.51 Setting up libgssapi-krb5-2:amd64 (1.21.3-5) ...
#9 16.51 Setting up libxrandr2:amd64 (2:1.5.4-1+b3) ...
#9 16.52 Setting up libssh-4:amd64 (0.11.2-1+deb13u1) ...
#9 16.52 Setting up librubberband2:amd64 (3.3.0+dfsg-2+b3) ...
#9 16.52 Setting up libjack-jackd2-0:amd64 (1.9.22~dfsg-4) ...
#9 16.52 Setting up libdrm2:amd64 (2.4.124-2) ...
#9 16.53 Setting up libva-drm2:amd64 (2.22.0-3) ...
#9 16.53 Setting up libvdpau1:amd64 (1.5-3+b1) ...
#9 16.54 Setting up libsord-0-0:amd64 (0.16.18-1) ...
#9 16.55 Setting up libwayland-cursor0:amd64 (1.23.1-3) ...
#9 16.55 Setting up libsratom-0-0:amd64 (0.6.18-1) ...
#9 16.55 Setting up libdecor-0-0:amd64 (0.2.2-2) ...
#9 16.55 Setting up libharfbuzz0b:amd64 (10.2.0-1+b1) ...
#9 16.55 Setting up libgdk-pixbuf-2.0-0:amd64 (2.42.12+dfsg-4) ...
#9 16.57 Setting up libxss1:amd64 (1:1.2.3-1+b3) ...
#9 16.57 Setting up libfontconfig1:amd64 (2.15.0-2.3) ...
#9 16.58 Setting up libsndfile1:amd64 (1.2.2-2+b1) ...
#9 16.58 Setting up libbluray2:amd64 (1:1.3.4-1+b2) ...
#9 16.58 Setting up libva-x11-2:amd64 (2.22.0-3) ...
#9 16.58 Setting up liblilv-0-0:amd64 (0.24.26-1) ...
#9 16.59 Setting up libopenmpt0t64:amd64 (0.7.13-1+b1) ...
#9 16.59 Setting up libdrm-amdgpu1:amd64 (2.4.124-2) ...
#9 16.59 Setting up libgnutls30t64:amd64 (3.8.9-3+deb13u2) ...
#9 16.59 Setting up fontconfig (2.15.0-2.3) ...
#9 16.60 Regenerating fonts cache... done.
#9 18.61 Setting up libzmq5:amd64 (4.3.5-1+b3) ...
#9 18.62 Setting up libxi6:amd64 (2:1.8.2-1) ...
#9 18.62 Setting up libpulse0:amd64 (17.0+dfsg1-2+b1) ...
#9 18.62 Setting up libxcursor1:amd64 (1:1.2.3-1) ...
#9 18.62 Setting up libpango-1.0-0:amd64 (1.56.3-1) ...
#9 18.63 Setting up libdrm-intel1:amd64 (2.4.124-2) ...
#9 18.63 Setting up libavutil59:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.63 Setting up libcairo2:amd64 (1.18.4-1+b1) ...
#9 18.63 Setting up libpostproc58:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.64 Setting up libsphinxbase3t64:amd64 (0.8+5prealpha+1-21+b1) ...
#9 18.64 Setting up libswresample5:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.64 Setting up libswscale8:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.64 Setting up libass9:amd64 (1:0.17.3-1+b1) ...
#9 18.65 Setting up libtheoradec1:amd64 (1.2.0~alpha1+dfsg-6) ...
#9 18.65 Setting up libsrt1.5-gnutls:amd64 (1.5.4-1) ...
#9 18.65 Setting up libcairo-gobject2:amd64 (1.18.4-1+b1) ...
#9 18.65 Setting up libpangoft2-1.0-0:amd64 (1.56.3-1) ...
#9 18.66 Setting up libpangocairo-1.0-0:amd64 (1.56.3-1) ...
#9 18.66 Setting up mesa-libgallium:amd64 (25.0.7-2) ...
#9 18.66 Setting up libgbm1:amd64 (25.0.7-2) ...
#9 18.66 Setting up libgl1-mesa-dri:amd64 (25.0.7-2) ...
#9 18.67 Setting up librsvg2-2:amd64 (2.60.0+dfsg-1) ...
#9 18.67 Setting up libpocketsphinx3:amd64 (0.8+5prealpha+1-15+b4) ...
#9 18.68 Setting up libavcodec61:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.68 Setting up libsdl2-2.0-0:amd64 (2.32.4+dfsg-1) ...
#9 18.68 Setting up libglx-mesa0:amd64 (25.0.7-2) ...
#9 18.68 Setting up libglx0:amd64 (1.7.0-1+b2) ...
#9 18.69 Setting up libavformat61:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.69 Setting up libgl1:amd64 (1.7.0-1+b2) ...
#9 18.69 Setting up libavfilter10:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.70 Setting up libavdevice61:amd64 (7:7.1.3-0+deb13u1) ...
#9 18.70 Setting up ffmpeg (7:7.1.3-0+deb13u1) ...
#9 18.70 Processing triggers for libc-bin (2.41-12+deb13u1) ...
#9 DONE 19.6s

#10 [ 4/10] COPY services/worker/requirements.txt ./requirements.txt
#10 DONE 0.0s

#11 [ 5/10] RUN pip install --no-cache-dir -r requirements.txt
#11 1.375 Collecting celery>=5.4.0 (from -r requirements.txt (line 1))
#11 1.407   Downloading celery-5.6.2-py3-none-any.whl.metadata (23 kB)
#11 1.462 Collecting redis>=5.0.0 (from -r requirements.txt (line 2))
#11 1.469   Downloading redis-7.2.1-py3-none-any.whl.metadata (12 kB)
#11 1.495 Collecting sqlmodel>=0.0.22 (from -r requirements.txt (line 3))
#11 1.504   Downloading sqlmodel-0.0.37-py3-none-any.whl.metadata (10 kB)
#11 1.529 Collecting pydantic-settings>=2.2.1 (from -r requirements.txt (line 4))
#11 1.536   Downloading pydantic_settings-2.13.1-py3-none-any.whl.metadata (3.4 kB)
#11 1.604 Collecting billiard<5.0,>=4.2.1 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.611   Downloading billiard-4.2.4-py3-none-any.whl.metadata (4.8 kB)
#11 1.660 Collecting kombu>=5.6.0 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.668   Downloading kombu-5.6.2-py3-none-any.whl.metadata (3.5 kB)
#11 1.687 Collecting vine<6.0,>=5.1.0 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.694   Downloading vine-5.1.0-py3-none-any.whl.metadata (2.7 kB)
#11 1.720 Collecting click<9.0,>=8.1.2 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.727   Downloading click-8.3.1-py3-none-any.whl.metadata (2.6 kB)
#11 1.742 Collecting click-didyoumean>=0.3.0 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.749   Downloading click_didyoumean-0.3.1-py3-none-any.whl.metadata (3.9 kB)
#11 1.764 Collecting click-repl>=0.2.0 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.771   Downloading click_repl-0.3.0-py3-none-any.whl.metadata (3.6 kB)
#11 1.786 Collecting click-plugins>=1.1.1 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.793   Downloading click_plugins-1.1.1.2-py2.py3-none-any.whl.metadata (6.5 kB)
#11 1.813 Collecting python-dateutil>=2.8.2 (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.820   Downloading python_dateutil-2.9.0.post0-py2.py3-none-any.whl.metadata (8.4 kB)
#11 1.842 Collecting tzlocal (from celery>=5.4.0->-r requirements.txt (line 1))
#11 1.849   Downloading tzlocal-5.3.1-py3-none-any.whl.metadata (7.6 kB)
#11 2.190 Collecting SQLAlchemy<2.1.0,>=2.0.14 (from sqlmodel>=0.0.22->-r requirements.txt (line 3))
#11 2.198   Downloading sqlalchemy-2.0.47-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (9.5 kB)
#11 2.341 Collecting pydantic>=2.11.0 (from sqlmodel>=0.0.22->-r requirements.txt (line 3))
#11 2.349   Downloading pydantic-2.12.5-py3-none-any.whl.metadata (90 kB)
#11 2.355      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 90.6/90.6 kB 17.7 MB/s eta 0:00:00
#11 2.398 Collecting python-dotenv>=0.21.0 (from pydantic-settings>=2.2.1->-r requirements.txt (line 4))
#11 2.405   Downloading python_dotenv-1.2.1-py3-none-any.whl.metadata (25 kB)
#11 2.427 Collecting typing-inspection>=0.4.0 (from pydantic-settings>=2.2.1->-r requirements.txt (line 4))
#11 2.434   Downloading typing_inspection-0.4.2-py3-none-any.whl.metadata (2.6 kB)
#11 2.494 Collecting prompt-toolkit>=3.0.36 (from click-repl>=0.2.0->celery>=5.4.0->-r requirements.txt (line 1))
#11 2.502   Downloading prompt_toolkit-3.0.52-py3-none-any.whl.metadata (6.4 kB)
#11 2.575 Collecting amqp<6.0.0,>=5.1.1 (from kombu>=5.6.0->celery>=5.4.0->-r requirements.txt (line 1))
#11 2.582   Downloading amqp-5.3.1-py3-none-any.whl.metadata (8.9 kB)
#11 2.606 Collecting tzdata>=2025.2 (from kombu>=5.6.0->celery>=5.4.0->-r requirements.txt (line 1))
#11 2.613   Downloading tzdata-2025.3-py2.py3-none-any.whl.metadata (1.4 kB)
#11 2.641 Collecting packaging (from kombu>=5.6.0->celery>=5.4.0->-r requirements.txt (line 1))
#11 2.648   Downloading packaging-26.0-py3-none-any.whl.metadata (3.3 kB)
#11 2.672 Collecting annotated-types>=0.6.0 (from pydantic>=2.11.0->sqlmodel>=0.0.22->-r requirements.txt (line 3))
#11 2.679   Downloading annotated_types-0.7.0-py3-none-any.whl.metadata (15 kB)
#11 3.413 Collecting pydantic-core==2.41.5 (from pydantic>=2.11.0->sqlmodel>=0.0.22->-r requirements.txt (line 3))
#11 3.420   Downloading pydantic_core-2.41.5-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (7.3 kB)
#11 3.446 Collecting typing-extensions>=4.14.1 (from pydantic>=2.11.0->sqlmodel>=0.0.22->-r requirements.txt (line 3))
#11 3.453   Downloading typing_extensions-4.15.0-py3-none-any.whl.metadata (3.3 kB)
#11 3.478 Collecting six>=1.5 (from python-dateutil>=2.8.2->celery>=5.4.0->-r requirements.txt (line 1))
#11 3.485   Downloading six-1.17.0-py2.py3-none-any.whl.metadata (1.7 kB)
#11 3.704 Collecting greenlet>=1 (from SQLAlchemy<2.1.0,>=2.0.14->sqlmodel>=0.0.22->-r requirements.txt (line 3))
#11 3.711   Downloading greenlet-3.3.2-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl.metadata (3.7 kB)
#11 3.762 Collecting wcwidth (from prompt-toolkit>=3.0.36->click-repl>=0.2.0->celery>=5.4.0->-r requirements.txt (line 1))
#11 3.769   Downloading wcwidth-0.6.0-py3-none-any.whl.metadata (30 kB)
#11 3.800 Downloading celery-5.6.2-py3-none-any.whl (445 kB)
#11 3.811    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 445.5/445.5 kB 48.5 MB/s eta 0:00:00
#11 3.819 Downloading redis-7.2.1-py3-none-any.whl (396 kB)
#11 3.822    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 396.1/396.1 kB 328.7 MB/s eta 0:00:00
#11 3.829 Downloading sqlmodel-0.0.37-py3-none-any.whl (27 kB)
#11 3.836 Downloading pydantic_settings-2.13.1-py3-none-any.whl (58 kB)
#11 3.838    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 58.9/58.9 kB 284.1 MB/s eta 0:00:00
#11 3.845 Downloading billiard-4.2.4-py3-none-any.whl (87 kB)
#11 3.846    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 87.1/87.1 kB 272.7 MB/s eta 0:00:00
#11 3.855 Downloading click-8.3.1-py3-none-any.whl (108 kB)
#11 3.857    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 108.3/108.3 kB 304.7 MB/s eta 0:00:00
#11 3.866 Downloading click_didyoumean-0.3.1-py3-none-any.whl (3.6 kB)
#11 3.873 Downloading click_plugins-1.1.1.2-py2.py3-none-any.whl (11 kB)
#11 3.880 Downloading click_repl-0.3.0-py3-none-any.whl (10 kB)
#11 3.887 Downloading kombu-5.6.2-py3-none-any.whl (214 kB)
#11 3.890    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 214.2/214.2 kB 318.9 MB/s eta 0:00:00
#11 3.897 Downloading vine-5.1.0-py3-none-any.whl (9.6 kB)
#11 3.904 Downloading pydantic-2.12.5-py3-none-any.whl (463 kB)
#11 3.908    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 463.6/463.6 kB 321.2 MB/s eta 0:00:00
#11 3.915 Downloading pydantic_core-2.41.5-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (2.1 MB)
#11 3.926    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.1/2.1 MB 220.1 MB/s eta 0:00:00
#11 3.933 Downloading python_dateutil-2.9.0.post0-py2.py3-none-any.whl (229 kB)
#11 3.936    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 229.9/229.9 kB 312.2 MB/s eta 0:00:00
#11 3.943 Downloading python_dotenv-1.2.1-py3-none-any.whl (21 kB)
#11 3.950 Downloading sqlalchemy-2.0.47-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (3.3 MB)
#11 3.975    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.3/3.3 MB 139.0 MB/s eta 0:00:00
#11 3.982 Downloading typing_inspection-0.4.2-py3-none-any.whl (14 kB)
#11 3.989 Downloading tzlocal-5.3.1-py3-none-any.whl (18 kB)
#11 3.996 Downloading amqp-5.3.1-py3-none-any.whl (50 kB)
#11 3.998    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 50.9/50.9 kB 273.4 MB/s eta 0:00:00
#11 4.005 Downloading annotated_types-0.7.0-py3-none-any.whl (13 kB)
#11 4.012 Downloading greenlet-3.3.2-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl (594 kB)
#11 4.016    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 594.2/594.2 kB 314.9 MB/s eta 0:00:00
#11 4.023 Downloading prompt_toolkit-3.0.52-py3-none-any.whl (391 kB)
#11 4.026    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 391.4/391.4 kB 324.1 MB/s eta 0:00:00
#11 4.033 Downloading six-1.17.0-py2.py3-none-any.whl (11 kB)
#11 4.040 Downloading typing_extensions-4.15.0-py3-none-any.whl (44 kB)
#11 4.042    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 44.6/44.6 kB 277.2 MB/s eta 0:00:00
#11 4.049 Downloading tzdata-2025.3-py2.py3-none-any.whl (348 kB)
#11 4.051    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 348.5/348.5 kB 351.7 MB/s eta 0:00:00
#11 4.058 Downloading packaging-26.0-py3-none-any.whl (74 kB)
#11 4.060    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 74.4/74.4 kB 294.7 MB/s eta 0:00:00
#11 4.066 Downloading wcwidth-0.6.0-py3-none-any.whl (94 kB)
#11 4.068    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 94.2/94.2 kB 281.5 MB/s eta 0:00:00
#11 4.257 Installing collected packages: wcwidth, vine, tzlocal, tzdata, typing-extensions, six, redis, python-dotenv, packaging, greenlet, click, billiard, annotated-types, typing-inspection, SQLAlchemy, python-dateutil, pydantic-core, prompt-toolkit, click-plugins, click-didyoumean, amqp, pydantic, kombu, click-repl, sqlmodel, pydantic-settings, celery
#11 6.911 Successfully installed SQLAlchemy-2.0.47 amqp-5.3.1 annotated-types-0.7.0 billiard-4.2.4 celery-5.6.2 click-8.3.1 click-didyoumean-0.3.1 click-plugins-1.1.1.2 click-repl-0.3.0 greenlet-3.3.2 kombu-5.6.2 packaging-26.0 prompt-toolkit-3.0.52 pydantic-2.12.5 pydantic-core-2.41.5 pydantic-settings-2.13.1 python-dateutil-2.9.0.post0 python-dotenv-1.2.1 redis-7.2.1 six-1.17.0 sqlmodel-0.0.37 typing-extensions-4.15.0 typing-inspection-0.4.2 tzdata-2025.3 tzlocal-5.3.1 vine-5.1.0 wcwidth-0.6.0
#11 6.911 WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv
#11 6.994 
#11 6.994 [notice] A new release of pip is available: 24.0 -> 26.0.1
#11 6.994 [notice] To update, run: pip install --upgrade pip
#11 DONE 7.4s

#12 [ 6/10] COPY packages/media-core /worker/packages/media-core
#12 DONE 0.0s

#13 [ 7/10] RUN pip install --no-cache-dir '/worker/packages/media-core[transcribe-faster-whisper,translate-local]'
#13 1.292 Processing ./packages/media-core
#13 1.295   Installing build dependencies: started
#13 3.796   Installing build dependencies: finished with status 'done'
#13 3.797   Getting requirements to build wheel: started
#13 4.276   Getting requirements to build wheel: finished with status 'done'
#13 4.277   Preparing metadata (pyproject.toml): started
#13 4.748   Preparing metadata (pyproject.toml): finished with status 'done'
#13 4.760 Requirement already satisfied: pydantic>=2.7 in /usr/local/lib/python3.11/site-packages (from media-core==0.1.0) (2.12.5)
#13 4.819 Collecting faster-whisper>=1.0.0 (from media-core==0.1.0)
#13 4.848   Downloading faster_whisper-1.2.1-py3-none-any.whl.metadata (16 kB)
#13 4.874 Collecting argostranslate>=1.9.0 (from media-core==0.1.0)
#13 4.881   Downloading argostranslate-1.11.0-py3-none-any.whl.metadata (9.7 kB)
#13 4.987 Collecting ctranslate2<5,>=4.0 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 4.996   Downloading ctranslate2-4.7.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (10 kB)
#13 5.014 Collecting minisbd (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.022   Downloading minisbd-0.9.3-py3-none-any.whl.metadata (47 kB)
#13 5.028      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 47.2/47.2 kB 9.1 MB/s eta 0:00:00
#13 5.037 Requirement already satisfied: packaging in /usr/local/lib/python3.11/site-packages (from argostranslate>=1.9.0->media-core==0.1.0) (26.0)
#13 5.063 Collecting sacremoses<0.2,>=0.0.53 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.071   Downloading sacremoses-0.1.1-py3-none-any.whl.metadata (8.3 kB)
#13 5.125 Collecting sentencepiece<0.3,>=0.2.0 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.133   Downloading sentencepiece-0.2.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (10 kB)
#13 5.266 Collecting spacy (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.273   Downloading spacy-3.8.11-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (27 kB)
#13 5.295 Collecting stanza==1.10.1 (from argostranslate>=1.9.0->media-core==0.1.0)
#13 5.303   Downloading stanza-1.10.1-py3-none-any.whl.metadata (13 kB)
#13 5.352 Collecting emoji (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 5.358   Downloading emoji-2.15.0-py3-none-any.whl.metadata (5.7 kB)
#13 5.566 Collecting numpy (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 5.573   Downloading numpy-2.4.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (6.6 kB)
#13 5.757 Collecting protobuf>=3.15.0 (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 5.764   Downloading protobuf-7.34.0-cp310-abi3-manylinux2014_x86_64.whl.metadata (595 bytes)
#13 5.798 Collecting requests (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 5.805   Downloading requests-2.32.5-py3-none-any.whl.metadata (4.9 kB)
#13 5.836 Collecting networkx (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 5.843   Downloading networkx-3.6.1-py3-none-any.whl.metadata (6.8 kB)
#13 5.921 Collecting torch>=1.3.0 (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 5.928   Downloading torch-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (31 kB)
#13 5.984 Collecting tqdm (from stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 5.991   Downloading tqdm-4.67.3-py3-none-any.whl.metadata (57 kB)
#13 5.993      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 57.7/57.7 kB 273.7 MB/s eta 0:00:00
#13 6.076 Collecting huggingface-hub>=0.21 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.083   Downloading huggingface_hub-1.5.0-py3-none-any.whl.metadata (13 kB)
#13 6.238 Collecting tokenizers<1,>=0.13 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.246   Downloading tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (7.3 kB)
#13 6.311 Collecting onnxruntime<2,>=1.14 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.318   Downloading onnxruntime-1.24.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (5.0 kB)
#13 6.370 Collecting av>=11 (from faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.379   Downloading av-16.1.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (4.6 kB)
#13 6.387 Requirement already satisfied: annotated-types>=0.6.0 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.7.0)
#13 6.388 Requirement already satisfied: pydantic-core==2.41.5 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (2.41.5)
#13 6.389 Requirement already satisfied: typing-extensions>=4.14.1 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (4.15.0)
#13 6.390 Requirement already satisfied: typing-inspection>=0.4.2 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.4.2)
#13 6.399 Requirement already satisfied: setuptools in /usr/local/lib/python3.11/site-packages (from ctranslate2<5,>=4.0->argostranslate>=1.9.0->media-core==0.1.0) (79.0.1)
#13 6.442 Collecting pyyaml<7,>=5.3 (from ctranslate2<5,>=4.0->argostranslate>=1.9.0->media-core==0.1.0)
#13 6.449   Downloading pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.4 kB)
#13 6.572 Collecting filelock>=3.10.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.579   Downloading filelock-3.24.3-py3-none-any.whl.metadata (2.0 kB)
#13 6.614 Collecting fsspec>=2023.5.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.620   Downloading fsspec-2026.2.0-py3-none-any.whl.metadata (10 kB)
#13 6.686 Collecting hf-xet<2.0.0,>=1.2.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.693   Downloading hf_xet-1.3.2-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (4.9 kB)
#13 6.723 Collecting httpx<1,>=0.23.0 (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.730   Downloading httpx-0.28.1-py3-none-any.whl.metadata (7.1 kB)
#13 6.773 Collecting typer (from huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.780   Downloading typer-0.24.1-py3-none-any.whl.metadata (16 kB)
#13 6.802 Collecting flatbuffers (from onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.809   Downloading flatbuffers-25.12.19-py2.py3-none-any.whl.metadata (1.0 kB)
#13 6.840 Collecting sympy (from onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 6.847   Downloading sympy-1.14.0-py3-none-any.whl.metadata (12 kB)
#13 7.280 Collecting regex (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.288   Downloading regex-2026.2.28-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (40 kB)
#13 7.290      ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.4/40.4 kB 260.7 MB/s eta 0:00:00
#13 7.293 Requirement already satisfied: click in /usr/local/lib/python3.11/site-packages (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0) (8.3.1)
#13 7.321 Collecting joblib (from sacremoses<0.2,>=0.0.53->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.329   Downloading joblib-1.5.3-py3-none-any.whl.metadata (5.5 kB)
#13 7.442 Collecting spacy-legacy<3.1.0,>=3.0.11 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.449   Downloading spacy_legacy-3.0.12-py2.py3-none-any.whl.metadata (2.8 kB)
#13 7.464 Collecting spacy-loggers<2.0.0,>=1.0.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.471   Downloading spacy_loggers-1.0.5-py3-none-any.whl.metadata (23 kB)
#13 7.514 Collecting murmurhash<1.1.0,>=0.28.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.521   Downloading murmurhash-1.0.15-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl.metadata (2.3 kB)
#13 7.563 Collecting cymem<2.1.0,>=2.0.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.570   Downloading cymem-2.0.13-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (9.7 kB)
#13 7.611 Collecting preshed<3.1.0,>=3.0.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.617   Downloading preshed-3.0.12-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl.metadata (2.5 kB)
#13 7.763 Collecting thinc<8.4.0,>=8.3.4 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.770   Downloading thinc-8.3.10-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (15 kB)
#13 7.791 Collecting wasabi<1.2.0,>=0.9.1 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.798   Downloading wasabi-1.1.3-py3-none-any.whl.metadata (28 kB)
#13 7.851 Collecting srsly<3.0.0,>=2.4.3 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.858   Downloading srsly-2.5.2-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (19 kB)
#13 7.881 Collecting catalogue<2.1.0,>=2.0.6 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.888   Downloading catalogue-2.0.10-py3-none-any.whl.metadata (14 kB)
#13 7.906 Collecting weasel<0.5.0,>=0.4.2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 7.913   Downloading weasel-0.4.3-py3-none-any.whl.metadata (4.6 kB)
#13 8.002 Collecting typer-slim<1.0.0,>=0.3.0 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.009   Downloading typer_slim-0.24.0-py3-none-any.whl.metadata (4.2 kB)
#13 8.074 Collecting jinja2 (from spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.081   Downloading jinja2-3.1.6-py3-none-any.whl.metadata (2.9 kB)
#13 8.185 Collecting anyio (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.192   Downloading anyio-4.12.1-py3-none-any.whl.metadata (4.3 kB)
#13 8.218 Collecting certifi (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.225   Downloading certifi-2026.2.25-py3-none-any.whl.metadata (2.5 kB)
#13 8.255 Collecting httpcore==1.* (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.263   Downloading httpcore-1.0.9-py3-none-any.whl.metadata (21 kB)
#13 8.283 Collecting idna (from httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.291   Downloading idna-3.11-py3-none-any.whl.metadata (8.4 kB)
#13 8.314 Collecting h11>=0.16 (from httpcore==1.*->httpx<1,>=0.23.0->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 8.321   Downloading h11-0.16.0-py3-none-any.whl.metadata (8.3 kB)
#13 8.443 Collecting charset_normalizer<4,>=2 (from requests->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.451   Downloading charset_normalizer-3.4.4-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (37 kB)
#13 8.502 Collecting urllib3<3,>=1.21.1 (from requests->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.509   Downloading urllib3-2.6.3-py3-none-any.whl.metadata (6.9 kB)
#13 8.614 Collecting blis<1.4.0,>=1.3.0 (from thinc<8.4.0,>=8.3.4->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.621   Downloading blis-1.3.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (7.5 kB)
#13 8.649 Collecting confection<1.0.0,>=0.0.1 (from thinc<8.4.0,>=8.3.4->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.656   Downloading confection-0.1.5-py3-none-any.whl.metadata (19 kB)
#13 8.746 Collecting cuda-bindings==12.9.4 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.754   Downloading cuda_bindings-12.9.4-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl.metadata (2.6 kB)
#13 8.773 Collecting nvidia-cuda-nvrtc-cu12==12.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.780   Downloading nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl.metadata (1.7 kB)
#13 8.800 Collecting nvidia-cuda-runtime-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.807   Downloading nvidia_cuda_runtime_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 8.826 Collecting nvidia-cuda-cupti-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.833   Downloading nvidia_cuda_cupti_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 8.857 Collecting nvidia-cudnn-cu12==9.10.2.21 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.864   Downloading nvidia_cudnn_cu12-9.10.2.21-py3-none-manylinux_2_27_x86_64.whl.metadata (1.8 kB)
#13 8.883 Collecting nvidia-cublas-cu12==12.8.4.1 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.890   Downloading nvidia_cublas_cu12-12.8.4.1-py3-none-manylinux_2_27_x86_64.whl.metadata (1.7 kB)
#13 8.910 Collecting nvidia-cufft-cu12==11.3.3.83 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.917   Downloading nvidia_cufft_cu12-11.3.3.83-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 8.937 Collecting nvidia-curand-cu12==10.3.9.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.946   Downloading nvidia_curand_cu12-10.3.9.90-py3-none-manylinux_2_27_x86_64.whl.metadata (1.7 kB)
#13 8.965 Collecting nvidia-cusolver-cu12==11.7.3.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.971   Downloading nvidia_cusolver_cu12-11.7.3.90-py3-none-manylinux_2_27_x86_64.whl.metadata (1.8 kB)
#13 8.992 Collecting nvidia-cusparse-cu12==12.5.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 8.998   Downloading nvidia_cusparse_cu12-12.5.8.93-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.8 kB)
#13 9.014 Collecting nvidia-cusparselt-cu12==0.7.1 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.021   Downloading nvidia_cusparselt_cu12-0.7.1-py3-none-manylinux2014_x86_64.whl.metadata (7.0 kB)
#13 9.040 Collecting nvidia-nccl-cu12==2.27.5 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.047   Downloading nvidia_nccl_cu12-2.27.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.0 kB)
#13 9.063 Collecting nvidia-nvshmem-cu12==3.4.5 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.070   Downloading nvidia_nvshmem_cu12-3.4.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (2.1 kB)
#13 9.089 Collecting nvidia-nvtx-cu12==12.8.90 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.096   Downloading nvidia_nvtx_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.8 kB)
#13 9.115 Collecting nvidia-nvjitlink-cu12==12.8.93 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.127   Downloading nvidia_nvjitlink_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl.metadata (1.7 kB)
#13 9.142 Collecting nvidia-cufile-cu12==1.13.1.3 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.149   Downloading nvidia_cufile_cu12-1.13.1.3-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (1.7 kB)
#13 9.171 Collecting triton==3.6.0 (from torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.180   Downloading triton-3.6.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (1.7 kB)
#13 9.208 Collecting cuda-pathfinder~=1.1 (from cuda-bindings==12.9.4->torch>=1.3.0->stanza==1.10.1->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.214   Downloading cuda_pathfinder-1.4.0-py3-none-any.whl.metadata (1.9 kB)
#13 9.372 Collecting mpmath<1.4,>=1.1.0 (from sympy->onnxruntime<2,>=1.14->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.379   Downloading mpmath-1.3.0-py3-none-any.whl.metadata (8.6 kB)
#13 9.422 Collecting shellingham>=1.3.0 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.429   Downloading shellingham-1.5.4-py2.py3-none-any.whl.metadata (3.5 kB)
#13 9.499 Collecting rich>=12.3.0 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.506   Downloading rich-14.3.3-py3-none-any.whl.metadata (18 kB)
#13 9.521 Collecting annotated-doc>=0.0.2 (from typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.529   Downloading annotated_doc-0.0.4-py3-none-any.whl.metadata (6.6 kB)
#13 9.582 Collecting cloudpathlib<1.0.0,>=0.7.0 (from weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.603   Downloading cloudpathlib-0.23.0-py3-none-any.whl.metadata (16 kB)
#13 9.631 Collecting smart-open<8.0.0,>=5.2.1 (from weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.638   Downloading smart_open-7.5.1-py3-none-any.whl.metadata (24 kB)
#13 9.725 Collecting MarkupSafe>=2.0 (from jinja2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 9.731   Downloading markupsafe-3.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (2.7 kB)
#13 9.917 Collecting markdown-it-py>=2.2.0 (from rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.924   Downloading markdown_it_py-4.0.0-py3-none-any.whl.metadata (7.3 kB)
#13 9.954 Collecting pygments<3.0.0,>=2.13.0 (from rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 9.961   Downloading pygments-2.19.2-py3-none-any.whl.metadata (2.5 kB)
#13 10.24 Collecting wrapt (from smart-open<8.0.0,>=5.2.1->weasel<0.5.0,>=0.4.2->spacy->argostranslate>=1.9.0->media-core==0.1.0)
#13 10.24   Downloading wrapt-2.1.1-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (7.4 kB)
#13 10.33 Collecting mdurl~=0.1 (from markdown-it-py>=2.2.0->rich>=12.3.0->typer->huggingface-hub>=0.21->faster-whisper>=1.0.0->media-core==0.1.0)
#13 10.34   Downloading mdurl-0.1.2-py3-none-any.whl.metadata (1.6 kB)
#13 10.39 Downloading argostranslate-1.11.0-py3-none-any.whl (41 kB)
#13 10.39    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 41.6/41.6 kB 195.5 MB/s eta 0:00:00
#13 10.40 Downloading stanza-1.10.1-py3-none-any.whl (1.1 MB)
#13 10.42    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 65.8 MB/s eta 0:00:00
#13 10.43 Downloading faster_whisper-1.2.1-py3-none-any.whl (1.1 MB)
#13 10.44    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 239.1 MB/s eta 0:00:00
#13 10.45 Downloading av-16.1.0-cp311-cp311-manylinux_2_28_x86_64.whl (40.8 MB)
#13 10.61    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.8/40.8 MB 268.3 MB/s eta 0:00:00
#13 10.62 Downloading ctranslate2-4.7.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (38.8 MB)
#13 10.77    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 38.8/38.8 MB 278.4 MB/s eta 0:00:00
#13 10.78 Downloading huggingface_hub-1.5.0-py3-none-any.whl (596 kB)
#13 10.78    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 596.3/596.3 kB 361.3 MB/s eta 0:00:00
#13 10.79 Downloading onnxruntime-1.24.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (17.1 MB)
#13 10.87    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 17.1/17.1 MB 240.5 MB/s eta 0:00:00
#13 10.88 Downloading sacremoses-0.1.1-py3-none-any.whl (897 kB)
#13 10.88    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 897.5/897.5 kB 354.8 MB/s eta 0:00:00
#13 10.89 Downloading sentencepiece-0.2.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (1.4 MB)
#13 10.90    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.4/1.4 MB 319.2 MB/s eta 0:00:00
#13 10.91 Downloading tokenizers-0.22.2-cp39-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (3.3 MB)
#13 10.92    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 3.3/3.3 MB 315.1 MB/s eta 0:00:00
#13 10.93 Downloading tqdm-4.67.3-py3-none-any.whl (78 kB)
#13 10.93    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.4/78.4 kB 307.8 MB/s eta 0:00:00
#13 10.94 Downloading minisbd-0.9.3-py3-none-any.whl (40 kB)
#13 10.94    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 40.9/40.9 kB 257.4 MB/s eta 0:00:00
#13 10.95 Downloading spacy-3.8.11-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (32.3 MB)
#13 11.09    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 32.3/32.3 MB 265.9 MB/s eta 0:00:00
#13 11.09 Downloading catalogue-2.0.10-py3-none-any.whl (17 kB)
#13 11.10 Downloading cymem-2.0.13-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (244 kB)
#13 11.10    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 244.5/244.5 kB 350.6 MB/s eta 0:00:00
#13 11.11 Downloading filelock-3.24.3-py3-none-any.whl (24 kB)
#13 11.12 Downloading fsspec-2026.2.0-py3-none-any.whl (202 kB)
#13 11.12    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 202.5/202.5 kB 328.3 MB/s eta 0:00:00
#13 11.13 Downloading hf_xet-1.3.2-cp37-abi3-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (4.2 MB)
#13 11.14    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.2/4.2 MB 306.9 MB/s eta 0:00:00
#13 11.15 Downloading httpx-0.28.1-py3-none-any.whl (73 kB)
#13 11.15    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 73.5/73.5 kB 220.8 MB/s eta 0:00:00
#13 11.16 Downloading httpcore-1.0.9-py3-none-any.whl (78 kB)
#13 11.16    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.8/78.8 kB 298.4 MB/s eta 0:00:00
#13 11.17 Downloading murmurhash-1.0.15-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl (128 kB)
#13 11.17    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 128.4/128.4 kB 330.0 MB/s eta 0:00:00
#13 11.18 Downloading numpy-2.4.2-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (16.9 MB)
#13 11.24    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 16.9/16.9 MB 325.0 MB/s eta 0:00:00
#13 11.25 Downloading preshed-3.0.12-cp311-cp311-manylinux1_x86_64.manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_5_x86_64.whl (824 kB)
#13 11.25    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 824.7/824.7 kB 340.9 MB/s eta 0:00:00
#13 11.26 Downloading protobuf-7.34.0-cp310-abi3-manylinux2014_x86_64.whl (324 kB)
#13 11.26    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 324.3/324.3 kB 318.3 MB/s eta 0:00:00
#13 11.27 Downloading pyyaml-6.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (806 kB)
#13 11.27    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 806.6/806.6 kB 340.8 MB/s eta 0:00:00
#13 11.28 Downloading requests-2.32.5-py3-none-any.whl (64 kB)
#13 11.28    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 64.7/64.7 kB 297.4 MB/s eta 0:00:00
#13 11.29 Downloading spacy_legacy-3.0.12-py2.py3-none-any.whl (29 kB)
#13 11.30 Downloading spacy_loggers-1.0.5-py3-none-any.whl (22 kB)
#13 11.31 Downloading srsly-2.5.2-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (1.1 MB)
#13 11.31    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.1/1.1 MB 306.4 MB/s eta 0:00:00
#13 11.32 Downloading thinc-8.3.10-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (4.1 MB)
#13 11.34    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 4.1/4.1 MB 219.8 MB/s eta 0:00:00
#13 11.35 Downloading torch-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl (915.6 MB)
#13 16.41    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 915.6/915.6 MB 156.2 MB/s eta 0:00:00
#13 16.41 Downloading cuda_bindings-12.9.4-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl (12.2 MB)
#13 16.52    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 12.2/12.2 MB 124.2 MB/s eta 0:00:00
#13 16.53 Downloading nvidia_cublas_cu12-12.8.4.1-py3-none-manylinux_2_27_x86_64.whl (594.3 MB)
#13 19.84    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 594.3/594.3 MB 319.1 MB/s eta 0:00:00
#13 19.85 Downloading nvidia_cuda_cupti_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (10.2 MB)
#13 19.90    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 10.2/10.2 MB 205.3 MB/s eta 0:00:00
#13 19.90 Downloading nvidia_cuda_nvrtc_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl (88.0 MB)
#13 20.43    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 88.0/88.0 MB 121.2 MB/s eta 0:00:00
#13 20.43 Downloading nvidia_cuda_runtime_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (954 kB)
#13 20.44    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 954.8/954.8 kB 334.8 MB/s eta 0:00:00
#13 20.45 Downloading nvidia_cudnn_cu12-9.10.2.21-py3-none-manylinux_2_27_x86_64.whl (706.8 MB)
#13 23.25    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 706.8/706.8 MB 272.8 MB/s eta 0:00:00
#13 23.26 Downloading nvidia_cufft_cu12-11.3.3.83-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (193.1 MB)
#13 24.20    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 193.1/193.1 MB 283.0 MB/s eta 0:00:00
#13 24.21 Downloading nvidia_cufile_cu12-1.13.1.3-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (1.2 MB)
#13 24.22    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.2/1.2 MB 277.3 MB/s eta 0:00:00
#13 24.23 Downloading nvidia_curand_cu12-10.3.9.90-py3-none-manylinux_2_27_x86_64.whl (63.6 MB)
#13 24.43    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 63.6/63.6 MB 340.5 MB/s eta 0:00:00
#13 24.43 Downloading nvidia_cusolver_cu12-11.7.3.90-py3-none-manylinux_2_27_x86_64.whl (267.5 MB)
#13 25.75    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 267.5/267.5 MB 305.1 MB/s eta 0:00:00
#13 25.76 Downloading nvidia_cusparse_cu12-12.5.8.93-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (288.2 MB)
#13 27.79    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 288.2/288.2 MB 210.0 MB/s eta 0:00:00
#13 27.79 Downloading nvidia_cusparselt_cu12-0.7.1-py3-none-manylinux2014_x86_64.whl (287.2 MB)
#13 28.88    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 287.2/287.2 MB 287.8 MB/s eta 0:00:00
#13 28.88 Downloading nvidia_nccl_cu12-2.27.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (322.3 MB)
#13 30.15    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 322.3/322.3 MB 185.7 MB/s eta 0:00:00
#13 30.15 Downloading nvidia_nvjitlink_cu12-12.8.93-py3-none-manylinux2010_x86_64.manylinux_2_12_x86_64.whl (39.3 MB)
#13 30.34    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 39.3/39.3 MB 292.8 MB/s eta 0:00:00
#13 30.34 Downloading nvidia_nvshmem_cu12-3.4.5-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (139.1 MB)
#13 31.20    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 139.1/139.1 MB 254.7 MB/s eta 0:00:00
#13 31.21 Downloading nvidia_nvtx_cu12-12.8.90-py3-none-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (89 kB)
#13 31.21    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 90.0/90.0 kB 317.6 MB/s eta 0:00:00
#13 31.22 Downloading triton-3.6.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (188.2 MB)
#13 32.16    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 188.2/188.2 MB 157.7 MB/s eta 0:00:00
#13 32.17 Downloading networkx-3.6.1-py3-none-any.whl (2.1 MB)
#13 32.18    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.1/2.1 MB 323.8 MB/s eta 0:00:00
#13 32.18 Downloading sympy-1.14.0-py3-none-any.whl (6.3 MB)
#13 32.21    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.3/6.3 MB 285.8 MB/s eta 0:00:00
#13 32.21 Downloading typer_slim-0.24.0-py3-none-any.whl (3.4 kB)
#13 32.22 Downloading typer-0.24.1-py3-none-any.whl (56 kB)
#13 32.22    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 56.1/56.1 kB 286.2 MB/s eta 0:00:00
#13 32.23 Downloading wasabi-1.1.3-py3-none-any.whl (27 kB)
#13 32.24 Downloading weasel-0.4.3-py3-none-any.whl (50 kB)
#13 32.24    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 50.8/50.8 kB 278.5 MB/s eta 0:00:00
#13 32.25 Downloading emoji-2.15.0-py3-none-any.whl (608 kB)
#13 32.25    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 608.4/608.4 kB 252.4 MB/s eta 0:00:00
#13 32.26 Downloading flatbuffers-25.12.19-py2.py3-none-any.whl (26 kB)
#13 32.27 Downloading jinja2-3.1.6-py3-none-any.whl (134 kB)
#13 32.27    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 134.9/134.9 kB 280.2 MB/s eta 0:00:00
#13 32.28 Downloading joblib-1.5.3-py3-none-any.whl (309 kB)
#13 32.28    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 309.1/309.1 kB 341.4 MB/s eta 0:00:00
#13 32.29 Downloading regex-2026.2.28-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (800 kB)
#13 32.29    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 800.2/800.2 kB 251.9 MB/s eta 0:00:00
#13 32.30 Downloading annotated_doc-0.0.4-py3-none-any.whl (5.3 kB)
#13 32.31 Downloading blis-1.3.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (11.4 MB)
#13 32.39    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 11.4/11.4 MB 140.7 MB/s eta 0:00:00
#13 32.40 Downloading certifi-2026.2.25-py3-none-any.whl (153 kB)
#13 32.40    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 153.7/153.7 kB 314.2 MB/s eta 0:00:00
#13 32.41 Downloading charset_normalizer-3.4.4-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (151 kB)
#13 32.41    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 151.6/151.6 kB 313.6 MB/s eta 0:00:00
#13 32.42 Downloading cloudpathlib-0.23.0-py3-none-any.whl (62 kB)
#13 32.42    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62.8/62.8 kB 285.2 MB/s eta 0:00:00
#13 32.42 Downloading confection-0.1.5-py3-none-any.whl (35 kB)
#13 32.43 Downloading idna-3.11-py3-none-any.whl (71 kB)
#13 32.43    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 71.0/71.0 kB 230.4 MB/s eta 0:00:00
#13 32.44 Downloading markupsafe-3.0.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (22 kB)
#13 32.45 Downloading mpmath-1.3.0-py3-none-any.whl (536 kB)
#13 32.45    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 536.2/536.2 kB 319.1 MB/s eta 0:00:00
#13 32.46 Downloading rich-14.3.3-py3-none-any.whl (310 kB)
#13 32.46    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 310.5/310.5 kB 324.9 MB/s eta 0:00:00
#13 32.47 Downloading shellingham-1.5.4-py2.py3-none-any.whl (9.8 kB)
#13 32.48 Downloading smart_open-7.5.1-py3-none-any.whl (64 kB)
#13 32.48    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 64.1/64.1 kB 296.8 MB/s eta 0:00:00
#13 32.48 Downloading urllib3-2.6.3-py3-none-any.whl (131 kB)
#13 32.49    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 131.6/131.6 kB 314.5 MB/s eta 0:00:00
#13 32.49 Downloading anyio-4.12.1-py3-none-any.whl (113 kB)
#13 32.50    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 113.6/113.6 kB 312.2 MB/s eta 0:00:00
#13 32.52 Downloading cuda_pathfinder-1.4.0-py3-none-any.whl (38 kB)
#13 32.52 Downloading h11-0.16.0-py3-none-any.whl (37 kB)
#13 32.53 Downloading markdown_it_py-4.0.0-py3-none-any.whl (87 kB)
#13 32.53    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 87.3/87.3 kB 300.8 MB/s eta 0:00:00
#13 32.54 Downloading pygments-2.19.2-py3-none-any.whl (1.2 MB)
#13 32.55    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.2/1.2 MB 328.5 MB/s eta 0:00:00
#13 32.57 Downloading wrapt-2.1.1-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (113 kB)
#13 32.57    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 113.9/113.9 kB 268.3 MB/s eta 0:00:00
#13 32.57 Downloading mdurl-0.1.2-py3-none-any.whl (10.0 kB)
#13 36.85 Building wheels for collected packages: media-core
#13 36.85   Building wheel for media-core (pyproject.toml): started
#13 37.35   Building wheel for media-core (pyproject.toml): finished with status 'done'
#13 37.35   Created wheel for media-core: filename=media_core-0.1.0-py3-none-any.whl size=32578 sha256=778f344837855e8dba13e97344f8097a20ee195f81859cba5a096ecdf19628b5
#13 37.35   Stored in directory: /tmp/pip-ephem-wheel-cache-vn4f8o3v/wheels/b3/1b/bb/820896c27a04aa0a1c42405a1e408db8e7a4c37ac4ee5b822f
#13 37.36 Successfully built media-core
#13 37.95 Installing collected packages: nvidia-cusparselt-cu12, mpmath, flatbuffers, wrapt, wasabi, urllib3, triton, tqdm, sympy, spacy-loggers, spacy-legacy, shellingham, sentencepiece, regex, pyyaml, pygments, protobuf, nvidia-nvtx-cu12, nvidia-nvshmem-cu12, nvidia-nvjitlink-cu12, nvidia-nccl-cu12, nvidia-curand-cu12, nvidia-cufile-cu12, nvidia-cuda-runtime-cu12, nvidia-cuda-nvrtc-cu12, nvidia-cuda-cupti-cu12, nvidia-cublas-cu12, numpy, networkx, murmurhash, mdurl, MarkupSafe, joblib, idna, hf-xet, h11, fsspec, filelock, emoji, cymem, cuda-pathfinder, cloudpathlib, charset_normalizer, certifi, catalogue, av, annotated-doc, srsly, smart-open, sacremoses, requests, preshed, onnxruntime, nvidia-cusparse-cu12, nvidia-cufft-cu12, nvidia-cudnn-cu12, markdown-it-py, jinja2, httpcore, cuda-bindings, ctranslate2, blis, anyio, rich, nvidia-cusolver-cu12, minisbd, media-core, httpx, confection, typer, torch, thinc, typer-slim, stanza, huggingface-hub, weasel, tokenizers, spacy, faster-whisper, argostranslate
#13 101.3 Successfully installed MarkupSafe-3.0.3 annotated-doc-0.0.4 anyio-4.12.1 argostranslate-1.11.0 av-16.1.0 blis-1.3.3 catalogue-2.0.10 certifi-2026.2.25 charset_normalizer-3.4.4 cloudpathlib-0.23.0 confection-0.1.5 ctranslate2-4.7.1 cuda-bindings-12.9.4 cuda-pathfinder-1.4.0 cymem-2.0.13 emoji-2.15.0 faster-whisper-1.2.1 filelock-3.24.3 flatbuffers-25.12.19 fsspec-2026.2.0 h11-0.16.0 hf-xet-1.3.2 httpcore-1.0.9 httpx-0.28.1 huggingface-hub-1.5.0 idna-3.11 jinja2-3.1.6 joblib-1.5.3 markdown-it-py-4.0.0 mdurl-0.1.2 media-core-0.1.0 minisbd-0.9.3 mpmath-1.3.0 murmurhash-1.0.15 networkx-3.6.1 numpy-2.4.2 nvidia-cublas-cu12-12.8.4.1 nvidia-cuda-cupti-cu12-12.8.90 nvidia-cuda-nvrtc-cu12-12.8.93 nvidia-cuda-runtime-cu12-12.8.90 nvidia-cudnn-cu12-9.10.2.21 nvidia-cufft-cu12-11.3.3.83 nvidia-cufile-cu12-1.13.1.3 nvidia-curand-cu12-10.3.9.90 nvidia-cusolver-cu12-11.7.3.90 nvidia-cusparse-cu12-12.5.8.93 nvidia-cusparselt-cu12-0.7.1 nvidia-nccl-cu12-2.27.5 nvidia-nvjitlink-cu12-12.8.93 nvidia-nvshmem-cu12-3.4.5 nvidia-nvtx-cu12-12.8.90 onnxruntime-1.24.2 preshed-3.0.12 protobuf-7.34.0 pygments-2.19.2 pyyaml-6.0.3 regex-2026.2.28 requests-2.32.5 rich-14.3.3 sacremoses-0.1.1 sentencepiece-0.2.1 shellingham-1.5.4 smart-open-7.5.1 spacy-3.8.11 spacy-legacy-3.0.12 spacy-loggers-1.0.5 srsly-2.5.2 stanza-1.10.1 sympy-1.14.0 thinc-8.3.10 tokenizers-0.22.2 torch-2.10.0 tqdm-4.67.3 triton-3.6.0 typer-0.24.1 typer-slim-0.24.0 urllib3-2.6.3 wasabi-1.1.3 weasel-0.4.3 wrapt-2.1.1
#13 101.3 WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv
#13 101.4 
#13 101.4 [notice] A new release of pip is available: 24.0 -> 26.0.1
#13 101.4 [notice] To update, run: pip install --upgrade pip
#13 DONE 105.7s

#14 [ 8/10] COPY apps/api /worker/apps/api
#14 DONE 0.0s

#15 [ 9/10] COPY services/worker /worker
#15 DONE 0.0s

#16 [10/10] COPY scripts /worker/scripts
#16 DONE 0.0s

#17 exporting to image
#17 exporting layers
#17 exporting layers 18.9s done
#17 writing image sha256:7294f32094550fc6caf8b0082a0630e88540d26bfcd333b5372478942a583fde done
#17 naming to docker.io/library/infra-worker done
#17 DONE 18.9s

#18 resolving provenance for metadata file
#18 DONE 0.0s
Processing ./packages/media-core
  Installing build dependencies: started
  Installing build dependencies: finished with status 'done'
  Getting requirements to build wheel: started
  Getting requirements to build wheel: finished with status 'done'
  Preparing metadata (pyproject.toml): started
  Preparing metadata (pyproject.toml): finished with status 'done'
Requirement already satisfied: pydantic>=2.7 in /usr/local/lib/python3.11/site-packages (from media-core==0.1.0) (2.12.5)
Collecting pyannote.audio>=3.1.1 (from media-core==0.1.0)
  Downloading pyannote_audio-4.0.4-py3-none-any.whl.metadata (13 kB)
Collecting asteroid-filterbanks>=0.4.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading asteroid_filterbanks-0.4.0-py3-none-any.whl.metadata (3.3 kB)
Collecting einops>=0.8.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading einops-0.8.2-py3-none-any.whl.metadata (13 kB)
Requirement already satisfied: huggingface-hub>=0.28.1 in /usr/local/lib/python3.11/site-packages (from pyannote.audio>=3.1.1->media-core==0.1.0) (1.5.0)
Collecting lightning>=2.4 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading lightning-2.6.1-py3-none-any.whl.metadata (44 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 44.8/44.8 kB 7.0 MB/s eta 0:00:00
Collecting matplotlib>=3.10.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading matplotlib-3.10.8-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (52 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 52.8/52.8 kB 156.4 MB/s eta 0:00:00
Collecting opentelemetry-api>=1.34.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_api-1.39.1-py3-none-any.whl.metadata (1.5 kB)
Collecting opentelemetry-exporter-otlp>=1.34.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp-1.39.1-py3-none-any.whl.metadata (2.4 kB)
Collecting opentelemetry-sdk>=1.34.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_sdk-1.39.1-py3-none-any.whl.metadata (1.5 kB)
Collecting pyannote-core>=6.0.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_core-6.0.1-py3-none-any.whl.metadata (1.9 kB)
Collecting pyannote-database>=6.1.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_database-6.1.1-py3-none-any.whl.metadata (30 kB)
Collecting pyannote-metrics>=4.0.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_metrics-4.0.0-py3-none-any.whl.metadata (2.2 kB)
Collecting pyannote-pipeline>=4.0.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannote_pipeline-4.0.0-py3-none-any.whl.metadata (5.4 kB)
Collecting pyannoteai-sdk>=0.3.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyannoteai_sdk-0.4.0-py3-none-any.whl.metadata (2.4 kB)
Collecting pytorch-metric-learning>=2.8.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pytorch_metric_learning-2.9.0-py3-none-any.whl.metadata (18 kB)
Requirement already satisfied: rich>=13.9.4 in /usr/local/lib/python3.11/site-packages (from pyannote.audio>=3.1.1->media-core==0.1.0) (14.3.3)
Collecting safetensors>=0.5.2 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl.metadata (4.1 kB)
Collecting torch-audiomentations>=0.12.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torch_audiomentations-0.12.0-py3-none-any.whl.metadata (15 kB)
Requirement already satisfied: torch>=2.8.0 in /usr/local/lib/python3.11/site-packages (from pyannote.audio>=3.1.1->media-core==0.1.0) (2.10.0)
Collecting torchaudio>=2.8.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torchaudio-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (6.9 kB)
Collecting torchcodec>=0.7.0 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torchcodec-0.10.0-cp311-cp311-manylinux_2_28_x86_64.whl.metadata (11 kB)
Collecting torchmetrics>=1.6.1 (from pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torchmetrics-1.8.2-py3-none-any.whl.metadata (22 kB)
Requirement already satisfied: annotated-types>=0.6.0 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.7.0)
Requirement already satisfied: pydantic-core==2.41.5 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (2.41.5)
Requirement already satisfied: typing-extensions>=4.14.1 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (4.15.0)
Requirement already satisfied: typing-inspection>=0.4.2 in /usr/local/lib/python3.11/site-packages (from pydantic>=2.7->media-core==0.1.0) (0.4.2)
Requirement already satisfied: numpy in /usr/local/lib/python3.11/site-packages (from asteroid-filterbanks>=0.4.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.4.2)
Requirement already satisfied: filelock>=3.10.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (3.24.3)
Requirement already satisfied: fsspec>=2023.5.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (2026.2.0)
Requirement already satisfied: hf-xet<2.0.0,>=1.2.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (1.3.2)
Requirement already satisfied: httpx<1,>=0.23.0 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.28.1)
Requirement already satisfied: packaging>=20.9 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (26.0)
Requirement already satisfied: pyyaml>=5.1 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (6.0.3)
Requirement already satisfied: tqdm>=4.42.1 in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (4.67.3)
Requirement already satisfied: typer in /usr/local/lib/python3.11/site-packages (from huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.24.1)
Collecting lightning-utilities<2.0,>=0.10.0 (from lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading lightning_utilities-0.15.3-py3-none-any.whl.metadata (5.5 kB)
Collecting pytorch-lightning (from lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pytorch_lightning-2.6.1-py3-none-any.whl.metadata (21 kB)
Collecting contourpy>=1.0.1 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading contourpy-1.3.3-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (5.5 kB)
Collecting cycler>=0.10 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading cycler-0.12.1-py3-none-any.whl.metadata (3.8 kB)
Collecting fonttools>=4.22.0 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading fonttools-4.61.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (114 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 114.2/114.2 kB 26.4 MB/s eta 0:00:00
Collecting kiwisolver>=1.3.1 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading kiwisolver-1.4.9-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (6.3 kB)
Collecting pillow>=8 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pillow-12.1.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (8.8 kB)
Collecting pyparsing>=3 (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pyparsing-3.3.2-py3-none-any.whl.metadata (5.8 kB)
Requirement already satisfied: python-dateutil>=2.7 in /usr/local/lib/python3.11/site-packages (from matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.9.0.post0)
Collecting importlib-metadata<8.8.0,>=6.0 (from opentelemetry-api>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading importlib_metadata-8.7.1-py3-none-any.whl.metadata (4.7 kB)
Collecting opentelemetry-exporter-otlp-proto-grpc==1.39.1 (from opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp_proto_grpc-1.39.1-py3-none-any.whl.metadata (2.5 kB)
Collecting opentelemetry-exporter-otlp-proto-http==1.39.1 (from opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp_proto_http-1.39.1-py3-none-any.whl.metadata (2.4 kB)
Collecting googleapis-common-protos~=1.57 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading googleapis_common_protos-1.72.0-py3-none-any.whl.metadata (9.4 kB)
Collecting grpcio<2.0.0,>=1.63.2 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading grpcio-1.78.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl.metadata (3.8 kB)
Collecting opentelemetry-exporter-otlp-proto-common==1.39.1 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_exporter_otlp_proto_common-1.39.1-py3-none-any.whl.metadata (1.8 kB)
Collecting opentelemetry-proto==1.39.1 (from opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_proto-1.39.1-py3-none-any.whl.metadata (2.3 kB)
Requirement already satisfied: requests~=2.7 in /usr/local/lib/python3.11/site-packages (from opentelemetry-exporter-otlp-proto-http==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.32.5)
Collecting protobuf<7.0,>=5.0 (from opentelemetry-proto==1.39.1->opentelemetry-exporter-otlp-proto-grpc==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading protobuf-6.33.5-cp39-abi3-manylinux2014_x86_64.whl.metadata (593 bytes)
Collecting opentelemetry-semantic-conventions==0.60b1 (from opentelemetry-sdk>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading opentelemetry_semantic_conventions-0.60b1-py3-none-any.whl.metadata (2.4 kB)
Collecting pandas>=2.2.3 (from pyannote-core>=6.0.1->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading pandas-3.0.1-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl.metadata (79 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 79.5/79.5 kB 307.6 MB/s eta 0:00:00
Collecting sortedcontainers>=2.4.0 (from pyannote-core>=6.0.1->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading sortedcontainers-2.4.0-py2.py3-none-any.whl.metadata (10 kB)
Collecting scikit-learn>=1.6.1 (from pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading scikit_learn-1.8.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (11 kB)
Collecting scipy>=1.15.1 (from pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading scipy-1.17.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl.metadata (62 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 62.1/62.1 kB 289.9 MB/s eta 0:00:00
Collecting optuna>=4.2.0 (from pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading optuna-4.7.0-py3-none-any.whl.metadata (17 kB)
Requirement already satisfied: markdown-it-py>=2.2.0 in /usr/local/lib/python3.11/site-packages (from rich>=13.9.4->pyannote.audio>=3.1.1->media-core==0.1.0) (4.0.0)
Requirement already satisfied: pygments<3.0.0,>=2.13.0 in /usr/local/lib/python3.11/site-packages (from rich>=13.9.4->pyannote.audio>=3.1.1->media-core==0.1.0) (2.19.2)
Requirement already satisfied: sympy>=1.13.3 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.14.0)
Requirement already satisfied: networkx>=2.5.1 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.6.1)
Requirement already satisfied: jinja2 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.1.6)
Requirement already satisfied: cuda-bindings==12.9.4 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.9.4)
Requirement already satisfied: nvidia-cuda-nvrtc-cu12==12.8.93 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.93)
Requirement already satisfied: nvidia-cuda-runtime-cu12==12.8.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.90)
Requirement already satisfied: nvidia-cuda-cupti-cu12==12.8.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.90)
Requirement already satisfied: nvidia-cudnn-cu12==9.10.2.21 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (9.10.2.21)
Requirement already satisfied: nvidia-cublas-cu12==12.8.4.1 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.4.1)
Requirement already satisfied: nvidia-cufft-cu12==11.3.3.83 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (11.3.3.83)
Requirement already satisfied: nvidia-curand-cu12==10.3.9.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (10.3.9.90)
Requirement already satisfied: nvidia-cusolver-cu12==11.7.3.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (11.7.3.90)
Requirement already satisfied: nvidia-cusparse-cu12==12.5.8.93 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.5.8.93)
Requirement already satisfied: nvidia-cusparselt-cu12==0.7.1 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (0.7.1)
Requirement already satisfied: nvidia-nccl-cu12==2.27.5 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.27.5)
Requirement already satisfied: nvidia-nvshmem-cu12==3.4.5 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.4.5)
Requirement already satisfied: nvidia-nvtx-cu12==12.8.90 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.90)
Requirement already satisfied: nvidia-nvjitlink-cu12==12.8.93 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (12.8.93)
Requirement already satisfied: nvidia-cufile-cu12==1.13.1.3 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.13.1.3)
Requirement already satisfied: triton==3.6.0 in /usr/local/lib/python3.11/site-packages (from torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.6.0)
Requirement already satisfied: cuda-pathfinder~=1.1 in /usr/local/lib/python3.11/site-packages (from cuda-bindings==12.9.4->torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.4.0)
Collecting julius<0.3,>=0.2.3 (from torch-audiomentations>=0.12.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading julius-0.2.7.tar.gz (59 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 59.6/59.6 kB 270.3 MB/s eta 0:00:00
  Preparing metadata (setup.py): started
  Preparing metadata (setup.py): finished with status 'done'
Collecting torch-pitch-shift>=1.2.2 (from torch-audiomentations>=0.12.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading torch_pitch_shift-1.2.5-py3-none-any.whl.metadata (2.5 kB)
Collecting aiohttp!=4.0.0a0,!=4.0.0a1 (from fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading aiohttp-3.13.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (8.1 kB)
Requirement already satisfied: anyio in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (4.12.1)
Requirement already satisfied: certifi in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (2026.2.25)
Requirement already satisfied: httpcore==1.* in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (1.0.9)
Requirement already satisfied: idna in /usr/local/lib/python3.11/site-packages (from httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (3.11)
Requirement already satisfied: h11>=0.16 in /usr/local/lib/python3.11/site-packages (from httpcore==1.*->httpx<1,>=0.23.0->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.16.0)
Collecting zipp>=3.20 (from importlib-metadata<8.8.0,>=6.0->opentelemetry-api>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading zipp-3.23.0-py3-none-any.whl.metadata (3.6 kB)
Requirement already satisfied: mdurl~=0.1 in /usr/local/lib/python3.11/site-packages (from markdown-it-py>=2.2.0->rich>=13.9.4->pyannote.audio>=3.1.1->media-core==0.1.0) (0.1.2)
Collecting alembic>=1.5.0 (from optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading alembic-1.18.4-py3-none-any.whl.metadata (7.2 kB)
Collecting colorlog (from optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading colorlog-6.10.1-py3-none-any.whl.metadata (11 kB)
Requirement already satisfied: sqlalchemy>=1.4.2 in /usr/local/lib/python3.11/site-packages (from optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.0.47)
Requirement already satisfied: six>=1.5 in /usr/local/lib/python3.11/site-packages (from python-dateutil>=2.7->matplotlib>=3.10.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.17.0)
Requirement already satisfied: charset_normalizer<4,>=2 in /usr/local/lib/python3.11/site-packages (from requests~=2.7->opentelemetry-exporter-otlp-proto-http==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.4.4)
Requirement already satisfied: urllib3<3,>=1.21.1 in /usr/local/lib/python3.11/site-packages (from requests~=2.7->opentelemetry-exporter-otlp-proto-http==1.39.1->opentelemetry-exporter-otlp>=1.34.0->pyannote.audio>=3.1.1->media-core==0.1.0) (2.6.3)
Requirement already satisfied: joblib>=1.3.0 in /usr/local/lib/python3.11/site-packages (from scikit-learn>=1.6.1->pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.5.3)
Collecting threadpoolctl>=3.2.0 (from scikit-learn>=1.6.1->pyannote-metrics>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading threadpoolctl-3.6.0-py3-none-any.whl.metadata (13 kB)
Requirement already satisfied: mpmath<1.4,>=1.1.0 in /usr/local/lib/python3.11/site-packages (from sympy>=1.13.3->torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (1.3.0)
Collecting primePy>=1.3 (from torch-pitch-shift>=1.2.2->torch-audiomentations>=0.12.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading primePy-1.3-py3-none-any.whl.metadata (4.8 kB)
Requirement already satisfied: MarkupSafe>=2.0 in /usr/local/lib/python3.11/site-packages (from jinja2->torch>=2.8.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.0.3)
Requirement already satisfied: click>=8.2.1 in /usr/local/lib/python3.11/site-packages (from typer->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (8.3.1)
Requirement already satisfied: shellingham>=1.3.0 in /usr/local/lib/python3.11/site-packages (from typer->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (1.5.4)
Requirement already satisfied: annotated-doc>=0.0.2 in /usr/local/lib/python3.11/site-packages (from typer->huggingface-hub>=0.28.1->pyannote.audio>=3.1.1->media-core==0.1.0) (0.0.4)
Collecting aiohappyeyeballs>=2.5.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading aiohappyeyeballs-2.6.1-py3-none-any.whl.metadata (5.9 kB)
Collecting aiosignal>=1.4.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading aiosignal-1.4.0-py3-none-any.whl.metadata (3.7 kB)
Collecting attrs>=17.3.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading attrs-25.4.0-py3-none-any.whl.metadata (10 kB)
Collecting frozenlist>=1.1.1 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading frozenlist-1.8.0-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl.metadata (20 kB)
Collecting multidict<7.0,>=4.5 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading multidict-6.7.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (5.3 kB)
Collecting propcache>=0.2.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading propcache-0.4.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (13 kB)
Collecting yarl<2.0,>=1.17.0 (from aiohttp!=4.0.0a0,!=4.0.0a1->fsspec[http]<2028.0,>=2022.5.0->lightning>=2.4->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading yarl-1.22.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl.metadata (75 kB)
     ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 75.1/75.1 kB 307.4 MB/s eta 0:00:00
Collecting Mako (from alembic>=1.5.0->optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0)
  Downloading mako-1.3.10-py3-none-any.whl.metadata (2.9 kB)
Requirement already satisfied: greenlet>=1 in /usr/local/lib/python3.11/site-packages (from sqlalchemy>=1.4.2->optuna>=4.2.0->pyannote-pipeline>=4.0.0->pyannote.audio>=3.1.1->media-core==0.1.0) (3.3.2)
Downloading pyannote_audio-4.0.4-py3-none-any.whl (893 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 893.7/893.7 kB 78.1 MB/s eta 0:00:00
Downloading asteroid_filterbanks-0.4.0-py3-none-any.whl (29 kB)
Downloading einops-0.8.2-py3-none-any.whl (65 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 65.6/65.6 kB 229.8 MB/s eta 0:00:00
Downloading lightning-2.6.1-py3-none-any.whl (853 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 853.6/853.6 kB 224.1 MB/s eta 0:00:00
Downloading matplotlib-3.10.8-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (8.7 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 8.7/8.7 MB 172.8 MB/s eta 0:00:00
Downloading opentelemetry_api-1.39.1-py3-none-any.whl (66 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 66.4/66.4 kB 283.6 MB/s eta 0:00:00
Downloading opentelemetry_exporter_otlp-1.39.1-py3-none-any.whl (7.0 kB)
Downloading opentelemetry_exporter_otlp_proto_grpc-1.39.1-py3-none-any.whl (19 kB)
Downloading opentelemetry_exporter_otlp_proto_http-1.39.1-py3-none-any.whl (19 kB)
Downloading opentelemetry_exporter_otlp_proto_common-1.39.1-py3-none-any.whl (18 kB)
Downloading opentelemetry_proto-1.39.1-py3-none-any.whl (72 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 72.5/72.5 kB 302.0 MB/s eta 0:00:00
Downloading opentelemetry_sdk-1.39.1-py3-none-any.whl (132 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 132.6/132.6 kB 326.0 MB/s eta 0:00:00
Downloading opentelemetry_semantic_conventions-0.60b1-py3-none-any.whl (219 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 220.0/220.0 kB 337.7 MB/s eta 0:00:00
Downloading pyannote_core-6.0.1-py3-none-any.whl (57 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 57.5/57.5 kB 280.4 MB/s eta 0:00:00
Downloading pyannote_database-6.1.1-py3-none-any.whl (53 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 53.7/53.7 kB 256.0 MB/s eta 0:00:00
Downloading pyannote_metrics-4.0.0-py3-none-any.whl (49 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 49.7/49.7 kB 278.7 MB/s eta 0:00:00
Downloading pyannote_pipeline-4.0.0-py3-none-any.whl (22 kB)
Downloading pyannoteai_sdk-0.4.0-py3-none-any.whl (8.9 kB)
Downloading pytorch_metric_learning-2.9.0-py3-none-any.whl (127 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 127.8/127.8 kB 297.2 MB/s eta 0:00:00
Downloading safetensors-0.7.0-cp38-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl (507 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 507.2/507.2 kB 349.8 MB/s eta 0:00:00
Downloading torch_audiomentations-0.12.0-py3-none-any.whl (48 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 48.5/48.5 kB 247.2 MB/s eta 0:00:00
Downloading torchaudio-2.10.0-cp311-cp311-manylinux_2_28_x86_64.whl (1.9 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.9/1.9 MB 323.7 MB/s eta 0:00:00
Downloading torchcodec-0.10.0-cp311-cp311-manylinux_2_28_x86_64.whl (2.1 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 2.1/2.1 MB 254.9 MB/s eta 0:00:00
Downloading torchmetrics-1.8.2-py3-none-any.whl (983 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 983.2/983.2 kB 243.7 MB/s eta 0:00:00
Downloading contourpy-1.3.3-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (355 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 355.2/355.2 kB 133.8 MB/s eta 0:00:00
Downloading cycler-0.12.1-py3-none-any.whl (8.3 kB)
Downloading fonttools-4.61.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (5.0 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 5.0/5.0 MB 215.9 MB/s eta 0:00:00
Downloading importlib_metadata-8.7.1-py3-none-any.whl (27 kB)
Downloading kiwisolver-1.4.9-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (1.4 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.4/1.4 MB 280.0 MB/s eta 0:00:00
Downloading lightning_utilities-0.15.3-py3-none-any.whl (31 kB)
Downloading optuna-4.7.0-py3-none-any.whl (413 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 413.9/413.9 kB 262.8 MB/s eta 0:00:00
Downloading pandas-3.0.1-cp311-cp311-manylinux_2_24_x86_64.manylinux_2_28_x86_64.whl (11.3 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 11.3/11.3 MB 264.4 MB/s eta 0:00:00
Downloading pillow-12.1.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (7.0 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 7.0/7.0 MB 295.5 MB/s eta 0:00:00
Downloading pyparsing-3.3.2-py3-none-any.whl (122 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 122.8/122.8 kB 345.6 MB/s eta 0:00:00
Downloading scikit_learn-1.8.0-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (9.1 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 9.1/9.1 MB 276.0 MB/s eta 0:00:00
Downloading scipy-1.17.1-cp311-cp311-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl (35.3 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 35.3/35.3 MB 282.1 MB/s eta 0:00:00
Downloading sortedcontainers-2.4.0-py2.py3-none-any.whl (29 kB)
Downloading torch_pitch_shift-1.2.5-py3-none-any.whl (5.0 kB)
Downloading pytorch_lightning-2.6.1-py3-none-any.whl (857 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 857.3/857.3 kB 71.4 MB/s eta 0:00:00
Downloading aiohttp-3.13.3-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (1.7 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 1.7/1.7 MB 304.5 MB/s eta 0:00:00
Downloading alembic-1.18.4-py3-none-any.whl (263 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 263.9/263.9 kB 328.0 MB/s eta 0:00:00
Downloading googleapis_common_protos-1.72.0-py3-none-any.whl (297 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 297.5/297.5 kB 350.6 MB/s eta 0:00:00
Downloading grpcio-1.78.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.whl (6.7 MB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 6.7/6.7 MB 337.6 MB/s eta 0:00:00
Downloading primePy-1.3-py3-none-any.whl (4.0 kB)
Downloading threadpoolctl-3.6.0-py3-none-any.whl (18 kB)
Downloading zipp-3.23.0-py3-none-any.whl (10 kB)
Downloading colorlog-6.10.1-py3-none-any.whl (11 kB)
Downloading aiohappyeyeballs-2.6.1-py3-none-any.whl (15 kB)
Downloading aiosignal-1.4.0-py3-none-any.whl (7.5 kB)
Downloading attrs-25.4.0-py3-none-any.whl (67 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 67.6/67.6 kB 293.6 MB/s eta 0:00:00
Downloading frozenlist-1.8.0-cp311-cp311-manylinux1_x86_64.manylinux_2_28_x86_64.manylinux_2_5_x86_64.whl (231 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 231.1/231.1 kB 348.9 MB/s eta 0:00:00
Downloading multidict-6.7.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (246 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 246.3/246.3 kB 334.5 MB/s eta 0:00:00
Downloading propcache-0.4.1-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (210 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 210.0/210.0 kB 291.0 MB/s eta 0:00:00
Downloading protobuf-6.33.5-cp39-abi3-manylinux2014_x86_64.whl (323 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 323.5/323.5 kB 312.7 MB/s eta 0:00:00
Downloading yarl-1.22.0-cp311-cp311-manylinux2014_x86_64.manylinux_2_17_x86_64.manylinux_2_28_x86_64.whl (365 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 365.8/365.8 kB 329.0 MB/s eta 0:00:00
Downloading mako-1.3.10-py3-none-any.whl (78 kB)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 78.5/78.5 kB 300.5 MB/s eta 0:00:00
Building wheels for collected packages: media-core, julius
  Building wheel for media-core (pyproject.toml): started
  Building wheel for media-core (pyproject.toml): finished with status 'done'
  Created wheel for media-core: filename=media_core-0.1.0-py3-none-any.whl size=32578 sha256=7f9c8a672924d7f1157e537beff5b19ccbf7ea92fa404c195368290f2433b5ba
  Stored in directory: /tmp/pip-ephem-wheel-cache-ymgcjd8h/wheels/b3/1b/bb/820896c27a04aa0a1c42405a1e408db8e7a4c37ac4ee5b822f
  Building wheel for julius (setup.py): started
  Building wheel for julius (setup.py): finished with status 'done'
  Created wheel for julius: filename=julius-0.2.7-py3-none-any.whl size=21966 sha256=f06da3e1ab88653797125a5b93d6209f80f4a42a5a087b7ba2d87885f859b789
  Stored in directory: /tmp/pip-ephem-wheel-cache-ymgcjd8h/wheels/16/15/d4/edd724cefe78050a6ba3344b8b0c6672db829a799dbb9f81ff
Successfully built media-core julius
Installing collected packages: sortedcontainers, primePy, zipp, torchcodec, threadpoolctl, scipy, safetensors, pyparsing, protobuf, propcache, pillow, multidict, Mako, lightning-utilities, kiwisolver, grpcio, frozenlist, fonttools, einops, cycler, contourpy, colorlog, attrs, aiohappyeyeballs, yarl, scikit-learn, pyannoteai-sdk, pandas, opentelemetry-proto, matplotlib, importlib-metadata, googleapis-common-protos, alembic, aiosignal, pyannote-core, optuna, opentelemetry-exporter-otlp-proto-common, opentelemetry-api, media-core, aiohttp, torchmetrics, torchaudio, pytorch-metric-learning, pyannote-database, opentelemetry-semantic-conventions, julius, asteroid-filterbanks, torch-pitch-shift, pytorch-lightning, pyannote-pipeline, pyannote-metrics, opentelemetry-sdk, torch-audiomentations, opentelemetry-exporter-otlp-proto-http, opentelemetry-exporter-otlp-proto-grpc, lightning, opentelemetry-exporter-otlp, pyannote.audio
  Attempting uninstall: protobuf
    Found existing installation: protobuf 7.34.0
    Uninstalling protobuf-7.34.0:
      Successfully uninstalled protobuf-7.34.0
  Attempting uninstall: media-core
    Found existing installation: media-core 0.1.0
    Uninstalling media-core-0.1.0:
      Successfully uninstalled media-core-0.1.0
Successfully installed Mako-1.3.10 aiohappyeyeballs-2.6.1 aiohttp-3.13.3 aiosignal-1.4.0 alembic-1.18.4 asteroid-filterbanks-0.4.0 attrs-25.4.0 colorlog-6.10.1 contourpy-1.3.3 cycler-0.12.1 einops-0.8.2 fonttools-4.61.1 frozenlist-1.8.0 googleapis-common-protos-1.72.0 grpcio-1.78.0 importlib-metadata-8.7.1 julius-0.2.7 kiwisolver-1.4.9 lightning-2.6.1 lightning-utilities-0.15.3 matplotlib-3.10.8 media-core-0.1.0 multidict-6.7.1 opentelemetry-api-1.39.1 opentelemetry-exporter-otlp-1.39.1 opentelemetry-exporter-otlp-proto-common-1.39.1 opentelemetry-exporter-otlp-proto-grpc-1.39.1 opentelemetry-exporter-otlp-proto-http-1.39.1 opentelemetry-proto-1.39.1 opentelemetry-sdk-1.39.1 opentelemetry-semantic-conventions-0.60b1 optuna-4.7.0 pandas-3.0.1 pillow-12.1.1 primePy-1.3 propcache-0.4.1 protobuf-6.33.5 pyannote-core-6.0.1 pyannote-database-6.1.1 pyannote-metrics-4.0.0 pyannote-pipeline-4.0.0 pyannote.audio-4.0.4 pyannoteai-sdk-0.4.0 pyparsing-3.3.2 pytorch-lightning-2.6.1 pytorch-metric-learning-2.9.0 safetensors-0.7.0 scikit-learn-1.8.0 scipy-1.17.1 sortedcontainers-2.4.0 threadpoolctl-3.6.0 torch-audiomentations-0.12.0 torch-pitch-shift-1.2.5 torchaudio-2.10.0 torchcodec-0.10.0 torchmetrics-1.8.2 yarl-1.22.0 zipp-3.23.0
WARNING: Running pip as the 'root' user can result in broken permissions and conflicting behaviour with the system package manager. It is recommended to use a virtual environment instead: https://pip.pypa.io/warnings/venv

[notice] A new release of pip is available: 24.0 -> 26.0.1
[notice] To update, run: pip install --upgrade pip
Warmup run (not timed)...
[0;93m2026-02-28 18:29:21.607047855 [W:onnxruntime:Default, device_discovery.cc:131 GetPciBusId] Skipping pci_bus_id for PCI path at "/sys/devices/LNXSYSTM:00/LNXSYBUS:00/ACPI0004:00/MSFT1000:00/5620e0c7-8062-4dce-aeb7-520c7ef76171" because filename ""5620e0c7-8062-4dce-aeb7-520c7ef76171"" dit not match expected pattern of [0-9a-f]+:[0-9a-f]+:[0-9a-f]+[.][0-9a-f]+[m

### Diarization benchmark

- backend: `pyannote`
- model: `pyannote/speaker-diarization-3.1`
- runs: `1` (warmup: `True`)
- duration_s_avg: `0.512` (min `0.512`, max `0.512`)
- segments_last_run: `0`
- peak_rss_mb: `1075.0`

```text
run=1 duration_s=0.512 segments=0
```
