#include "mpi.h"

#include "emdata.h"

#include "sirt_Cart.h"
#include "utilcomm_Cart.h"
#include "project3d.h"

#define PI 3.14159265358979

using namespace EMAN;

// Reconstruct the 3-D density of a macromolecule from
// a stack of 2-D images using the SIRT algorithm
//
// MPI Parallel Implementation using Cartesian virtual topology

int main(int argc, char ** argv)
{
   MPI_Comm comm = MPI_COMM_WORLD;
   int ncpus, mypid, ierr;
   int nloc; 
   double t0;
   FILE *fp;
   MPI_Comm comm_2d, comm_row, comm_col;

   MPI_Status mpistatus;
   MPI_Init(&argc,&argv);
   MPI_Comm_size(comm,&ncpus);
   MPI_Comm_rank(comm,&mypid);

  int ROW = 0, COL = 1;
  int dims[2], periods[2], my2dpid, mycoords[2];
  int srpid, srcoords[2], keep_dims[2];

   char  stackfname[100],voutfname[100], angfname[100];
   EMData **expimages;

   // parse the command line and set filenames	
   if (argc < 5) {
     if (mypid == 0) {
         printf("Not enough arguments to the command...\n");
         printf("Usage: runsirt -data=<imagestack> ");
         printf("-angles=<initial 3D volume> "); 
         printf("-out=<output filename base string> ");
         printf("-rowdim=<row dimension of Cartesian topology> ");
         printf("-coldim=<column dimension of Cartesian topology> ");
     }
     ierr = MPI_Finalize();
     exit(1);
   }
   int ia=0;
   while (ia < argc) {
      if ( !strncmp(argv[ia],"-data",5) ) {
         strcpy(stackfname,&argv[ia][6]);
      }
      else if ( !strncmp(argv[ia],"-angles",7) ) {
         strcpy(angfname,&argv[ia][8]);
      }
      else if ( !strncmp(argv[ia],"-out",4) ) {
         strcpy(voutfname,&argv[ia][5]);
      }
      else if ( !strncmp(argv[ia],"-rowdim",7) ) {
         dims[ROW] = atoi(&argv[ia][8]); // Row dimension of the topology
      }
      else if ( !strncmp(argv[ia],"-coldim",7) ) {
         dims[COL] = atoi(&argv[ia][8]); // Column dimension of the topology
      }
      ia++;
   }

  if (dims[ROW]*dims[COL] != ncpus){
	printf("ERROR: rowdim*coldim != ncpus\n");
	return -1;
  }

// Set up the Cartesian virtual topology: comm_2d
  periods[ROW] = periods[COL] = 1; // Set the periods for wrap-around
  MPI_Cart_create(comm, 2, dims, periods, 1, &comm_2d);
  MPI_Comm_rank(comm_2d, &my2dpid); //Get my pid in the new 2D topology
  MPI_Cart_coords(comm_2d, my2dpid, 2, mycoords); // Get my coordinates
  
 // printf("MPI_2d: mypid = %d, my2dpid = %d, mycoords = [%d, %d] \n", mypid, my2dpid, mycoords[ROW], mycoords[COL]);

  /* Create the row-based sub-topology */ 
  keep_dims[ROW] = 0; 
  keep_dims[COL] = 1; 
  MPI_Cart_sub(comm_2d, keep_dims, &comm_row); 

  /* Create the column-based sub-topology */ 
  keep_dims[ROW] = 1; 
  keep_dims[COL] = 0; 
  MPI_Cart_sub(comm_2d, keep_dims, &comm_col); 

   // read and distribute a stack of experimental images along row processors
   t0 = MPI_Wtime();
   ierr = ReadStackandDist_Cart(comm_2d, &expimages, stackfname, &nloc);
   if (ierr == 0) {
	if (mypid == 0) {
	   printf("Finished reading and distributing image stack onto Cartesian topology\n");
	   printf("I/O time for reading image stack = %11.3e\n",
		  MPI_Wtime() - t0);
	}
   }
   else {
      if (mypid == 0) 
         printf("Failed to read the image stack %s! exit...\n",stackfname);
      ierr = MPI_Finalize();
      exit(1);
   }

   // make a copy of the images for removing the background; 
   // this stack will be used for reconstruction
   EMData** cleanimages = new EMData*[nloc];
   for ( int i = 0 ; i < nloc ; ++i) {
	cleanimages[i] = expimages[i]->copy();
   }

   int nx = cleanimages[0]->get_xsize();
   int ny = cleanimages[0]->get_ysize();
   int nz = nx;

   Vec3i volsize;
   Vec3i origin;
   volsize[0] = nx;
   volsize[1] = ny;
   volsize[2] = nz;
   origin[0] = nx/2 + 1;
   origin[1] = ny/2 + 1;
   origin[2] = nz/2 + 1;
   int ri = nx/2 - 2;

   ierr = CleanStack_Cart(comm_col, cleanimages, nloc, ri, volsize, origin);

   // read angle and shift data and distribute along first column
   float * angleshift = new float[5*nloc];
   float * iobuffer   = new float[5*nloc];
   int nimgs=0;

   ierr = 0;
   if (mycoords[COL] == 0 && mycoords[ROW] == 0) { //I am Proc (0,0)
      fp = fopen(angfname,"r");
      if (!fp)  ierr = 1;
   }
   MPI_Bcast(&ierr, 1, MPI_INT, 0, comm);

   if ( ierr ) {
      if (mypid ==0) fprintf(stderr,"failed to open %s\n", angfname);
      ierr = MPI_Finalize();
      return 1; 
   }
   else {
       if (mycoords[COL] == 0 && mycoords[ROW] == 0) { //I am Proc (0,0)
	  for (int iproc = 0; iproc < dims[ROW]; iproc++) {
	     // figure out the number of images assigned to processor (iproc,0)
	     if (iproc > 0) {
		srcoords[COL] = 0;
		srcoords[ROW] = iproc;
		MPI_Cart_rank(comm_2d, srcoords, &srpid);

		MPI_Recv(&nimgs, 1, MPI_INT, srpid, srpid, comm_2d, &mpistatus);

		// Read the next nimgs set of angles and shifts
		for (int i = 0; i < nimgs; i++) {
		   fscanf(fp,"%f %f %f %f %f", 
			  &iobuffer[5*i+0],
			  &iobuffer[5*i+1],
			  &iobuffer[5*i+2],
			  &iobuffer[5*i+3],
			  &iobuffer[5*i+4]);
		}
		MPI_Send(iobuffer,5*nimgs,MPI_FLOAT,srpid,srpid,comm_2d);
	     }
	     else {
		for (int i = 0; i < nloc; i++) {
		   fscanf(fp,"%f %f %f %f %f", 
			  &angleshift[5*i+0],
			  &angleshift[5*i+1],
			  &angleshift[5*i+2],
			  &angleshift[5*i+3],
			  &angleshift[5*i+4]);
		}
	     }
	  }
	  fclose(fp);
       }
       else if (mycoords[COL] == 0 && mycoords[ROW] != 0) { //I am in the first column
	  // send image count to the master processor (mypid = 0)

	  MPI_Send(&nloc, 1, MPI_INT, 0, my2dpid, comm_2d);
	  // Receive angleshifts
	  MPI_Recv(angleshift, 5*nloc, MPI_FLOAT, 0, my2dpid, comm_2d, &mpistatus);
       }
  }

  // Now have all the processors in group g_c_0 broadcast the angles along the row communicator
  srcoords[ROW] = 0;
  MPI_Cart_rank(comm_row, srcoords, &srpid);
  MPI_Bcast(angleshift, 5*nloc, MPI_FLOAT, srpid, comm_row);

   EMDeleteArray(iobuffer);

   // Use xvol to hold reconstructed volume
   EMData * xvol = new EMData();

   // set SIRT parameters
   int maxit = 20;
   float lam = 5.0e-6;
   float tol = 1.0e-3;
   std::string symmetry = "c1";

   // call SIRT to reconstruct
   t0 = MPI_Wtime();
   recons3d_sirt_mpi_Cart(comm_2d, comm_row, comm_col, cleanimages, angleshift, xvol, nloc, ri, 
                     lam, maxit, symmetry, tol);

   if ( my2dpid == 0 ) 
       printf("Done with SIRT: time = %11.3e\n", MPI_Wtime() - t0);

   // write the reconstructed volume to disk
   EMUtil::ImageType WRITE_SPI = EMUtil::IMAGE_SINGLE_SPIDER;
   if ( my2dpid == 0 ) {
	xvol->write_image(voutfname, 0, WRITE_SPI);
   }

   // cleanup
   for ( int i = 0 ; i < nloc; ++i ) {
       EMDeletePtr(expimages[i]);
   }
   EMDeleteArray(expimages);
   for ( int i = 0 ; i < nloc; ++i ) {
       EMDeletePtr(cleanimages[i]);
   }
   EMDeleteArray(cleanimages);

   EMDeletePtr(xvol);
   EMDeleteArray(angleshift);

   ierr = MPI_Finalize();

   return 0; // main
}
